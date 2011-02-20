"Create RDKit fingerprints"

# Copyright (c) 2010 Andrew Dalke Scientific, AB (Gothenburg, Sweden)
# See the contents of "__init__.py" for full license details.

from __future__ import absolute_import

import os
import sys
import gzip

import rdkit
from rdkit import Chem
from rdkit.Chem.MACCSkeys import GenMACCSKeys


from . import sdf_reader, decoders, error_handlers, io

# These are the things I consider to be public
__all__ = ["read_structures", "iter_smiles_molecules", "iter_sdf_molecules"]

######## Some shenanigans to get a version field

if hasattr(rdkit, "version"):
    # This will be available in the next release of RDKit
    SOFTWARE = "RDKit/" + rdkit.version()
else:
    # This distribution does not have version().
    # Guess based on the evidence.

    # This was added in Release_Q22009_1
    import rdkit.Chem.AtomPairs.Torsions
    if not hasattr(Chem.AtomPairs.Torsions, "GetHashedTopologicalTorsionFingerprint"):
        SOFTWARE = "RDKit/unknown"
    else:
        # Either Release_Q22009_1 or Release_Q32009_1
        # Q3 removed the DaylightFingerprint function.
        if hasattr(Chem, "DaylightFingerprint"):
            # In 2010 the version numbers were put into lexical order.
            # Keep with the same principle.
            SOFTWARE = "RDKit/2009Q2_1"
        else:
            SOFTWARE = "RDKit/2009Q3_1"

##### Convert from RDKit explicit (dense) fingerprints to byte strings



#########
_allowed_formats = ["sdf", "smi"]
_format_extensions = {
    ".sdf": "sdf",
    ".mol": "sdf",
    ".sd": "sdf",
    ".mdl": "sdf",

    ".smi": "smi",
    ".can": "smi",
    ".smiles": "smi",
    ".ism": "smi",
}


class SmilesFileLocation(object):
    def __init__(self, name=None):
        self.name = name
        self.lineno = 1
    def where(self):
        s = "at line {self.lineno}"
        if self.name is not None:
            s += " of {self.name}"
        return s.format(self=self)
    

# While RDKit has a SMILES file parser, it doesn't handle reading from
# stdin or from compressed files. I wanted to support those as well, so
# ended up not using Chem.SmilesMolSupplier.

def iter_smiles_molecules(fileobj, name=None, errors="strict"):
    """Iterate over the SMILES file records, returning (title, RDKit.Chem.Mol) pairs

    'fileobj' is an input file or any line iterable
    'name' is the name used to report errors (if not specified, use
       fileobj.name if present)
    'errors' is one of "strict" (default), "log", or "ignore" (other values are experimental)

    Each line of the input must at least one whitespace separated
    fields.  The first field is the SMILES. If there is a second field
    then it is used as the title, otherwise the title is the current
    record number, starting with "1".

    """
    if name is None:
        name = getattr(fileobj, "name", None)
    error_handler = error_handlers.get_parse_error_handler(errors)

    loc = SmilesFileLocation(name)
    for lineno, line in enumerate(fileobj):
        words = line.split()
        if not words:
            loc.lineno = lineno+1
            error_handler("unexpected blank line", loc)
            continue

        mol = Chem.MolFromSmiles(words[0])
        if mol is None:
            loc.lineno = lineno+1
            error_handler("Cannot parse the SMILES %r" % (words[0],), loc)
            continue
        
        if len(words) == 1:
            yield str(lineno+1), mol
        else:
            yield words[1], mol


def iter_sdf_molecules(fileobj, name=None, errors="strict"):
    """Iterate over the SD file records, returning (title, Chem.Mol) pairs

    fileobj - the input file object
    name - the name to use to report errors. If None, use fileobj.name .
    
    """
    # If there's no explicit filename, see if fileobj has one
    if name is None:
        name = getattr(fileobj, "name", None)
    loc = sdf_reader.FileLocation(name)
    error = error_handlers.get_parse_error_handler(errors)
    for text in sdf_reader.iter_sdf_records(fileobj, errors, loc):
        mol = Chem.MolFromMolBlock(text)
        if mol is None:
            # This was not a molecule?
            error("Could not parse molecule block", loc)
        else:
            yield mol.GetProp("_Name"), mol

# This class helps the case when someone is entering structure
# by-hand. (Most likely to occur with SMILES input). They would like
# to see the result as soon as a record is entered. But normal
# interation reader grabs a buffer of input to process, and not a
# line. It's faster that way. The following adapter supports the
# iterator protocol but turns it into simple readlines(). This will be
# slower but since do it only if stdin is a tty, there shouldn't be a
# problem.
## class _IterUsingReadline(object):
##     "Internal class for iterating a line at a time from tty input"
##     def __init__(self, fileobj):
##         self.fileobj = fileobj
##     def __iter__(self):
##         return iter(self.fileobj.readline, "")

## def _open(filename, compressed):
##     "Internal function to open the given filename, which might be compressed"
##     if filename is None:
##         if compressed:
##             return gzip.GzipFile(fileobj=sys.stdin, mode="r")
##         else:
##             # Python's iter reads a block.
##             # When someone types interactively, read only a line.
##             if sys.stdin.isatty():
##                 return _IterUsingReadline(sys.stdin)
##             else:
##                 return sys.stdin

##     if compressed:
##         return gzip.GzipFile(filename, "r")
##     return open(filename, "rU")
    

def read_structures(source, format=None, errors="strict"):
    """Iterate the records in the input source as (title, RDKit.Chem.Mol) pairs

    'source' is a filename, a file object, or None for stdin
    'format' is either "sdf" or "smi" with optional ".gz" or ".bz2" extensions.
        If None then the format is inferred from the source extension
    'errors' is one of "strict" (default), "log", or "ignore" (other values are experimental)
    """
    format_name, compression = io.normalize_format(source, format, default=("smi", None))
    format_name = _format_extensions.get(format_name, format_name)
    if format_name == "sdf":
        # I have an old PubChem file Compound_09425001_09450000.sdf .
        #   num. lines = 5,041,475   num. bytes = 159,404,037
        # 
        # Parse times for iter_sdf_records (parsing records in Python)
        #   37.6s (best of 37.6, 38.3, 37.8)
        # Parse times for the RDKit implementation (parsing records in C++)
        #   40.2s (best of 41.7, 41.33, 40.2)
        # 
        # The native RDKit reader is slower than the Python one and does
        # not have (that I can tell) support for compressed files, so
        # I'll go with the Python one. For those interested, here's the
        # RDKit version.
        # 
        #if (not compressed) and (source is not None):
        #    supplier = Chem.SDMolSupplier(source)
        #    def native_sdf_reader():
        #        for mol in supplier:
        #            if mol is None:
        #                print >>sys.stderr, "Missing? after", title
        #            else:
        #                title = mol.GetProp("_Name")
        #                yield title, mol
        #    return native_sdf_reader()

        fileobj = io.open_compressed_input_universal(source, compression)
        # fileobj should always have the .name attribute set.
        return iter_sdf_molecules(fileobj, None, errors)

    elif format_name == "smi":
        # I timed the native reader at 31.6 seconds (best of 31.6, 31.7, 31.7)
        # and the Python reader at 30.8 seconds (best of 30.8, 30.9, and 31.0)
        # Yes, the Python reader is faster and using it gives me better consistency
        #
        #if (not compressed) and (source is not None):
        #    supplier = Chem.SmilesMolSupplier(source, delimiter=" \t", titleLine=False)
        #    def native_smiles_reader():
        #        for mol in supplier:
        #            yield mol.GetProp("_Name"), mol
        #    return native_smiles_reader()
        fileobj = io.open_compressed_input_universal(source, compression)
        return iter_smiles_molecules(fileobj, None, errors)

    else:
        raise TypeError("Unsupported format {format!r}".format(format=format))

########### The topological fingerprinter

# Some constants shared by the fingerprinter and the command-line code.

NUM_BITS = 2048
MIN_PATH = 1
MAX_PATH = 7
BITS_PER_HASH = 4
USE_HS = 1
assert USE_HS == 1, "Don't make this 0 unless you know what you are doing"

# Not supporting the tgtDensity and minSize options.
# This program generates fixed-length fingerprints.

def make_rdk_fingerprinter(minPath=MIN_PATH, maxPath=MAX_PATH, fpSize=NUM_BITS,
                           nBitsPerHash=BITS_PER_HASH, useHs=USE_HS):
    if not (fpSize > 0):
        raise TypeError("fpSize must be positive")
    if not (minPath > 0):
        raise TypeError("minPath must be positive")
    if not (maxPath >= minPath):
        raise TypeError("maxPath cannot be smaller than minPath")
    if not (nBitsPerHash > 0):
        raise TypeError("nBitsPerHash must be positive")

    def rdk_fingerprinter(mol):
        fp = Chem.RDKFingerprint(
            mol, minPath=minPath, maxPath=maxPath, fpSize=fpSize,
            nBitsPerHash=nBitsPerHash, useHs=useHs)
        return decoders.from_binary_lsb(fp.ToBitString())[1]
    return rdk_fingerprinter


########### The MACCS fingerprinter


def maccs166_fingerprinter(mol):
    fp = GenMACCSKeys(mol)
    # In RDKit the first bit is always bit 1 .. bit 0 is empty (?!?!)
    bitstring_with_167_bits = fp.ToBitString()
    return decoders.from_binary_lsb(bitstring_with_167_bits[1:])[1]


def read_maccs166_fingerprints_v1(source=None, format=None, kwargs={}):
    assert not kwargs
    fingerprinter = maccs166_fingerprinter
    reader = read_structures(source, format)
    def read_rdkit_maccs166_fingerprints():
        for (title, mol) in reader:
            yield (fingerprinter(mol), title)

    return read_rdkit_maccs166_fingerprints()

def read_rdkit_fingerprints_v1(source=None, format=None, kwargs={}):
    fingerprinter = make_rdk_fingerprinter(**kwargs)
    reader = read_structures(source, format)
    def read_rdkit_fingerprints():
        for (title, mol) in reader:
            yield (fingerprinter(mol), title)

    return read_rdkit_fingerprints()
