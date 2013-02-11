"Create Open Babel fingerprints"

# Copyright (c) 2010-2013 Andrew Dalke Scientific, AB (Gothenburg, Sweden)
# See the contents of "__init__.py" for full license details.

from __future__ import absolute_import

import sys
import os
import struct
import warnings
import itertools

import sys
import openbabel as ob

from . import ParseError
from . import io
from . import types
from . import error_handlers


# OpenBabel really wants these two variables. I get a segfault if
# BABEL_LIBDIR isn't defined, and from the mailing list, some of the
# code doesn't work correctly without BABEL_DATADIR. I've had problems
# where I forget to set these variables, so check for them now and
# warn about possible problems.

#if "BABEL_LIBDIR" not in os.environ:
#    warnings.warn("BABEL_LIBDIR is not set")

#else:
#  ... check that SMILES and a few other things are on the path ...
#  but note that BABEL_LIBDIR is a colon (or newline or control-return?)
#  separated field whose behaviour isn't well defined in the docs.
#  I'm not going to do additional checking without a stronger need.


# This is the only thing which I consider to be public
__all__ = ["read_structures"]

# This is a "standard" size according to the struct module
# documentation, so the following is an excess of caution
if struct.calcsize("<I") != 4:
    raise AssertionError("The chemfp.ob module assumes 32 bit integers")


# OpenBabel 2.2 doesn't expose "obErrorLog" to Python
HAS_ERROR_LOG = hasattr(ob, "obErrorLog")

# In OpenBabel 2.3.0, OBConversion() must be called before trying to
# find any plugin. This was not needed in earlier releases.
ob.OBConversion()

# OpenBabel before 2.3 didn't have a function to return the version.
# I've brought this up on the list, and it's in 2.3. I can fake
# support for older lists by reading the PDB output text.

def _emulated_OBReleaseVersion():
    "GetReleaseVersion() -> the version string for the OpenBabel toolkit"
    obconversion = ob.OBConversion()
    obconversion.SetInFormat("smi")
    obconversion.SetOutFormat("pdb")
    obmol = ob.OBMol()
    
    obconversion.ReadString(obmol, "C")
    for line in obconversion.WriteString(obmol).splitlines():
        if "GENERATED BY OPEN BABEL" in line:
            return line.split()[-1]
    return "<unknown>"

try:
    from openbabel import OBReleaseVersion
except ImportError:
    OBReleaseVersion = _emulated_OBReleaseVersion
_ob_version = OBReleaseVersion()

SOFTWARE = "OpenBabel/" + _ob_version


# OpenBabel fingerprints are stored as vector<unsigned int>.  On all
# the machines I use, ints have 32 bits.

# OpenBabel bit lengths must be at least sizeof(int)*8 bits long and
# must be a factor of two. I have no idea why this is required.

# OpenBabel supports new fingerprints through a plugin system.  I got
# it working thanks to Noel O'Boyle's excellent work with Cinfony. I
# then found out that the OB API doesn't have any way to get the
# number of bits in the fingerprint. The size is rounded up to the
# next power of two, so FP4 (307 bits) needs 512 bits (16 ints)
# instead of 320 bits (10 ints). That means I can't even get close to
# guessing the bitsize.

# In the end, I hard-coded the supported fingerprints into the system.



############

# I could have written a more general function which created these but
# there's only a few fingerprints lengths to worry about.

# This needs 128 bytes, for 1024 bits
# vectorUnsignedInt will contain 32 32-bit words = 1024 bits

_ob_get_fingerprint = {}
def _init():
    # 
    ob.OBConversion()
    for name in ("FP2", "FP3", "FP4", "MACCS"):
        ob_fingerprinter = ob.OBFingerprint.FindFingerprint(name)
        if ob_fingerprinter is None:
            _ob_get_fingerprint[name] = (None, None)
        else:
            _ob_get_fingerprint[name] = (ob_fingerprinter, ob_fingerprinter.GetFingerprint)

    if _ob_get_fingerprint["FP2"][0] is None:
        raise ImportError("Unable to load OpenBabel FP2 fingerprinter. Check $BABEL_LIBDIR")
    n = _ob_get_fingerprint["FP2"][0].Getbitsperint()
    if n != 32:
        raise AssertionError(
            "The chemfp.ob module assumes OB fingerprints have 32 bit integers")
            
_init()

def calc_FP2(mol, fp=None,
             get_fingerprint=_ob_get_fingerprint["FP2"][1],
             _pack_1024 = struct.Struct("<" + "I"*32).pack):
    if fp is None:
        fp = ob.vectorUnsignedInt()
    get_fingerprint(mol, fp)
    return _pack_1024(*fp)

# This needs 7 bytes, for 56 bits.
# vectorUnsignedInt will contain 2 32-bit words = 64 bits
def calc_FP3(mol, fp=None,
             get_fingerprint=_ob_get_fingerprint["FP3"][1],
             _pack_64 = struct.Struct("<II").pack):
    if fp is None:
        fp = ob.vectorUnsignedInt()
    get_fingerprint(mol, fp)
    return _pack_64(*fp)[:7]

# This needs 39 bytes, for 312 bits
# vectorUnsignedInt will contain 16 32-bit words = 512 bits
def calc_FP4(mol, fp=None,
             get_fingerprint=_ob_get_fingerprint["FP4"][1],
             _pack_512 = struct.Struct("<" + "I"*16).pack):
    if fp is None:
        fp = ob.vectorUnsignedInt()
    get_fingerprint(mol, fp)
    return _pack_512(*fp)[:39]

# This needs 21 bytes, for 166 bits
# vectorUnsignedInt will contain 8 32-bit words = 256 bits
# (Remember, although 6 words * 32-bits/word = 192, the OpenBabel
# fingerprint size must be a power of 2, and the closest is 8*32.)
def calc_MACCS(mol, fp=None,
               get_fingerprint=_ob_get_fingerprint["MACCS"][1],
               _pack_256 = struct.Struct("<" + "I"*8).pack):
    if fp is None:
        fp = ob.vectorUnsignedInt()
    get_fingerprint(mol, fp)
    return _pack_256(*fp)[:21]


# OpenBabel version up to 2.3.0 contained errors in the
# translation of the MACCS patterns from RDKit.
# Post-2.3.0 fixed in version control.
# MACCS might also be missing if BABEL_DATADIR doesn't exist.
HAS_MACCS = False
MACCS_VERSION = 0

def _check_for_maccs():
    global HAS_MACCS, MACCS_VERSION
    if _ob_get_fingerprint["MACCS"] == (None, None):
        if _ob_version.startswith("2.2."):
            return
        # MACCS should be here. Report the most likely reason
        if "BABEL_DATADIR" not in os.environ:
            warnings.warn("MACCS fingerprint missing; perhaps due to missing BABEL_DATADIR?")
        else:
            warnings.warn("MACCS fingerprint missing; perhaps due to BABEL_DATADIR?")
        return

    HAS_MACCS = 1

    # OpenBabel 2.3.0 released the MACCS keys but with a bug in the SMARTS.
    # While they are valid substructure keys, they are not really MACCS keys.
    # This is a run-time detection to figure out which version was installed
    obconversion = ob.OBConversion()
    obconversion.SetInFormat("smi")
    obmol = ob.OBMol()
    obconversion.ReadString(obmol, "CC1=CC(=NN1CC(=O)NNC(=O)C=CC2=C(C=CC=C2Cl)F)C")
    fp = calc_MACCS(obmol)
    if fp == "\x80\x04\x00\x00\x00\x02\x08\x00\x19\xc4@\xea\xcdl\x98\x0b\xae\xa1x\xef\x1b":
        MACCS_VERSION = 1
    elif fp == "\x00\x00\x00\x00\x00\x02\x08\x00\x19\xc4D\xea\xcdl\x98\x0b\xae\xa1x\xef\x1f":
        MACCS_VERSION = 2
    else:
        raise AssertionError("Unknown MACCS fingerprint version: %r" % (fp,))

_check_for_maccs()


#########

def is_valid_format(format):
    if format is None:
        return True
    try:
        format_name, compression = io.normalize_format(None, format, ("smi", ""))
    except ValueError:
        return False
    if compression not in ("", ".gz"):
        return False
    obconversion = ob.OBConversion()
    if not obconversion.SetInFormat(format_name):
        return False
    return True

def _get_ob_error(log):
    msgs = log.GetMessagesOfLevel(ob.obError)
    return "".join(msgs)

def read_structures(filename=None, format=None, id_tag=None, errors="strict"):
    """read_structures(filename, format) -> (id, OBMol) iterator 
    
    Iterate over structures from filename, returning the structure
    title and OBMol for each record. The structure is assumed to be
    in normalized_format(filename, format) format. If filename is None
    then this reads from stdin instead of the named file.
    """
    if not (filename is None or isinstance(filename, basestring)):
        raise TypeError("'filename' must be None or a string")
    error_handler = error_handlers.get_parse_error_handler(errors)
    
    obconversion = ob.OBConversion()
    format_name, compression = io.normalize_format(filename, format,
                                                   default=("smi", ""))
    if compression not in ("", ".gz"):
        raise ValueError("Unsupported compression type for %r" % (filename,))

    # OpenBabel auto-detects gzip compression.

    if not obconversion.SetInFormat(format_name):
        raise ValueError("Unknown structure format %r" % (format_name,))
    
    obmol = ob.OBMol()

    if not filename:
        filename = io.DEV_STDIN
        if filename is None:
            raise NotImplementedError("Unable to read from stdin on this operating system")
        success = obconversion.ReadFile(obmol, filename)
        filename_repr = "<stdin>"
         
    else:
        
        # Deal with OpenBabel's logging
        if HAS_ERROR_LOG:
            ob.obErrorLog.ClearLog()
            lvl = ob.obErrorLog.GetOutputLevel()
            ob.obErrorLog.SetOutputLevel(-1) # Suppress messages to stderr

        success = obconversion.ReadFile(obmol, filename)
        filename_repr = repr(filename)

        errmsg = None
        if HAS_ERROR_LOG:
            ob.obErrorLog.SetOutputLevel(lvl) # Restore message level
            if ob.obErrorLog.GetErrorMessageCount():
                errmsg = _get_ob_error(ob.obErrorLog)

        if not success:
            # Either there was an error or there were no structures.
            open(filename).close() # Make sure the file can be opened for reading

            # If I get here then the file exists and is readable.

            # If there was an error message then use it.
            if errmsg is not None:
                # Okay, don't know what's going on. Report OB's error
                raise IOError(5, errmsg, filename)

    # We've opened the file. Switch to the iterator.
    return _file_reader(obconversion, obmol, success, id_tag, filename_repr, error_handler)

def _file_reader(obconversion, obmol, success, id_tag, filename_repr, error_handler):
    def where():
        return " for record #%d of %s" % (recno, filename_repr)
    
    # How do I detect if the input contains a failure?
    recno = 0
    if id_tag is None:
        while success:
            recno += 1
            title = obmol.GetTitle()
            id = io.remove_special_characters_from_id(title)
            if not id:
                error_handler("Missing title" + where())
            else:
                yield id, obmol
                
            obmol.Clear()
            success = obconversion.Read(obmol)

    else:
        while success:
            recno += 1
            obj = obmol.GetData(id_tag)
            if obj is None:
                error_handler("Missing id tag %r%s" % (id_tag, where()))
            else:
                dirty_id = obj.GetValue()
                id = io.remove_special_characters_from_id(dirty_id)
                if not id:
                    msg = "Empty id tag %r" % (id_tag,)
                    error_handler(msg + where())
                else:
                    yield id, obmol
                    
            obmol.Clear()
            success = obconversion.Read(obmol)

#####

from .types import FingerprintFamilyConfig

def _read_structures(metadata, source, format, id_tag, errors):
    if metadata.aromaticity is not None:
        raise ValueError("Open Babel does not support alternate aromaticity models "
                         "(want aromaticity=%r)" % metadata.aromaticity)
    return read_structures(source, format, id_tag, errors)

_base = FingerprintFamilyConfig(
    software = SOFTWARE,
    read_structures = _read_structures,
    )


OpenBabelFP2FingerprintFamily_v1 = _base.clone(
    name = "OpenBabel-FP2/1",
    num_bits = 1021,
    make_fingerprinter = lambda: calc_FP2)

OpenBabelFP3FingerprintFamily_v1 = _base.clone(
    name = "OpenBabel-FP3/1",
    num_bits = 55,
    make_fingerprinter = lambda: calc_FP3)

OpenBabelFP4FingerprintFamily_v1 = _base.clone(
    name = "OpenBabel-FP4/1",
    num_bits = 307,
    make_fingerprinter = lambda: calc_FP4)


def _check_calc_MACCS_v1():
    assert HAS_MACCS
    assert MACCS_VERSION == 1
    return calc_MACCS

OpenBabelMACCSFingerprintFamily_v1 = _base.clone(
    name = "OpenBabel-MACCS/1",
    num_bits = 166,
    make_fingerprinter = _check_calc_MACCS_v1)


def _check_calc_MACCS_v2():
    assert HAS_MACCS
    assert MACCS_VERSION == 2
    return calc_MACCS
    
OpenBabelMACCSFingerprintFamily_v2 = _base.clone(
    name = "OpenBabel-MACCS/2",
    num_bits = 166,
    make_fingerprinter = _check_calc_MACCS_v2)
