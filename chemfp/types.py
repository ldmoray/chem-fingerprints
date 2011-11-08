# Information about fingerprint types

from . import FingerprintIterator, Metadata

from . import io
from .decoders import import_decoder  # XXX too specific to the decoder module


def check_openbabel_maccs166():
    from chemfp.openbabel import HAS_MACCS, MACCS_VERSION
    assert HAS_MACCS
    if MACCS_VERSION == 1:
        return "OpenBabel-MACCS/1"
    elif MACCS_VERSION == 2:
        return "OpenBabel-MACCS/2"
    raise AssertionError

class FingerprintFamily(object):
    def __init__(self, family_name, path):
        self.family_name = family_name
        self.path = path

    def __call__(self, **kwargs):
        cls = import_decoder(self.path)
        assert cls.name == self.family_name
        return cls(kwargs)

    def from_parameters(self, parameters):
        cls = import_decoder(self.path)
        assert cls.name == self.family_name
        return cls.from_parameters(parameters)

_families = [
    FingerprintFamily("OpenEye-MACCS166/1", "chemfp.openeye.OpenEyeMACCSFingerprinter_v1"),
    FingerprintFamily("OpenEye-Path/1", "chemfp.openeye.OpenEyePathFingerprinter_v1"),
    
    FingerprintFamily("RDKit-MACCS166/1", "chemfp.rdkit.RDKitMACCSFingerprinter_v1"),
    FingerprintFamily("RDKit-Fingerprint/1", "chemfp.rdkit.RDKitFingerprinter_v1"),
    
    FingerprintFamily("OpenBabel-FP2/1", "chemfp.openbabel.OpenBabelFP2Fingerprinter_v1"),
    FingerprintFamily("OpenBabel-FP3/1", "chemfp.openbabel.OpenBabelFP3Fingerprinter_v1"),
    FingerprintFamily("OpenBabel-FP4/1", "chemfp.openbabel.OpenBabelFP4Fingerprinter_v1"),
    FingerprintFamily("OpenBabel-MACCS/1", "chemfp.openbabel.OpenBabelMACCSFingerprinter_v1"),
    FingerprintFamily("OpenBabel-MACCS/2", "chemfp.openbabel.OpenBabelMACCSFingerprinter_v2"),

    FingerprintFamily("Indigo-Similarity/1", "chemfp.indigo.IndigoSimilarityFingerprinter_v1"),
    FingerprintFamily("Indigo-Substructure/1",
                      "chemfp.indigo.IndigoSubstructureFingerprinter_v1"),
    FingerprintFamily("Indigo-ResonanceSubstructure/1",
                      "chemfp.indigo.IndigoResonanceSubstructureFingerprinter_v1"),
    FingerprintFamily("Indigo-TautomerSubstructure/1",
                      "chemfp.indigo.IndigoTautomerSubstructureFingerprinter_v1"),
    FingerprintFamily("Indigo-Full/1", "chemfp.indigo.IndigoFullFingerprinter_v1"),

    # In the future this will likely change to use a parameterized class
    # which can dynamically load fingerprint definitions

    FingerprintFamily("ChemFP-Substruct-OpenEye/1",
                      "chemfp.openeye_patterns.SubstructOpenEyeFingerprinter_v1"),
    FingerprintFamily("RDMACCS-OpenEye/1",
                      "chemfp.openeye_patterns.RDMACCSOpenEyeFingerprinter_v1"),

    FingerprintFamily("ChemFP-Substruct-RDKit/1",
                      "chemfp.rdkit_patterns.SubstructRDKitFingerprinter_v1"),
    FingerprintFamily("RDMACCS-RDKit/1",
                      "chemfp.rdkit_patterns.RDMACCSRDKitFingerprinter_v1"),

    FingerprintFamily("ChemFP-Substruct-OpenBabel/1",
                      "chemfp.openbabel_patterns.SubstructOpenBabelFingerprinter_v1"),
    FingerprintFamily("RDMACCS-OpenBabel/1",
                      "chemfp.openbabel_patterns.RDMACCSOpenBabelFingerprinter_v1"),

    FingerprintFamily("ChemFP-Substruct-Indigo/1",
                      "chemfp.indigo_patterns.SubstructIndigoFingerprinter_v1"),
    FingerprintFamily("RDMACCS-Indigo/1",
                      "chemfp.indigo_patterns.RDMACCSIndigoFingerprinter_v1"),
]

_alternates = {
    "OpenBabel-MACCS": check_openbabel_maccs166
    }


_family_by_name = {}

def _initialize_families():
    for family in _families:
        # Set both the versioned and non-versioned names
        name = family.family_name
        unversioned_name = name.split("/")[0]
        _family_by_name[name] = _family_by_name[unversioned_name] = family

    # Don't include a (likely non-versioned) name if there's a selector function
    for name in _alternates:
        if name in _family_by_name:
            del _family_by_name[name]

_initialize_families()


def get_fingerprint_family(name):
    try:
        return _family_by_name[name]
    except KeyError:
        if name not in _alternates:
            raise
    alternate = _alternates[name]()
    return _family_by_name[alternate]

class Fingerprinter(object):
    format_string = None
    software = None
    def __init__(self, fingerprinter_kwargs):
        self.fingerprinter_kwargs = fingerprinter_kwargs
        # Some self-test code to make sure preconditions are met
        # This means they must be set before calling super().__init__
        if getattr(self, "name", None) is None:
            raise AssertionError("num_bits not defined (%r)" % (self.__class__,))
        if getattr(self, "num_bits", None) is None:
            raise AssertionError("num_bits not defined (%r)" % (self.name,))
        if getattr(self, "num_bits", None) is None:
            raise AssertionError("num_bits not defined (%r)" % (self.name,))
        if getattr(self, "software", None) is None:
            raise AssertionError("software not defined (%r)" % (self.name,))

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.fingerprinter_kwargs)

    def __eq__(self, other):
        return self.get_type() == other.get_type()

    def __ne__(self, other):
        return self.get_type() != other.get_type()

    @classmethod
    def from_parameters(cls, parameters):
        if parameters:
            raise AssertionError  # should be implemented in the client
        return cls({})


    # Subclasses may hook into this
    def _encode_parameters(self):
        # Assume they can be interpreted directly in the format_string
        return self.fingerprinter_kwargs

    def get_type(self):
        if self.format_string is None:
            assert not self.fingerprinter_kwargs, "kwargs but no format string!"
            return self.name
        encoded = self.format_string % self._encode_parameters()
        return self.name + " " + encoded

    # Subclasses must hook into this
    def _read_structures(self, metadata, source, format, id_tag, errors):
        raise NotImplementedError("Subclass %r must implement _read_structures" % (self.__class__.__name__,))

    # Subclasses must hook into this
    def _get_fingerprinter(self, **fingerprinter_kwargs):
        raise NotImplementedError("Subclasses %r must implement _get_fingerprinter" % (self.__class__.__name__,))
    
    def read_structure_fingerprints(self, source, format=None, id_tag=None, errors="strict", metadata=None):
        source_filename = io.get_filename(source)
        if source_filename is None:
            sources = []
        else:
            sources = [source_filename]
            
        if metadata is None:
            # XXX I don't like how the user who wants to pass in aromaticity
            # information needs to create the full Metadata
            metadata = Metadata(num_bits=self.num_bits, type=self.get_type(),
                                software=self.software,
                                sources=sources)
            
        structure_reader = self._read_structures(metadata, source, format, id_tag, errors)
        fingerprinter = self._get_fingerprinter(**self.fingerprinter_kwargs)

        def fingerprint_reader(structure_reader, fingerprinter):
            for (id, mol) in structure_reader:
                yield id, fingerprinter(mol)
        reader = fingerprint_reader(structure_reader, fingerprinter)
        
        return FingerprintIterator(Metadata(num_bits = self.num_bits,
                                            sources = sources,
                                            software = self.software,
                                            type = self.get_type(),
                                            date = io.utcnow(),
                                            aromaticity = metadata.aromaticity),
                                   reader)
    
    def describe(self, bitno):
        if 0 <= bitno < self.num_bits:
            return "bit %d (unknown)" % (bitno,)
        raise KeyError(bitno)
        

def parse_type(type):
    terms = type.split()
    if not terms:
        raise ValueError("missing name")

    name = terms[0]
    try:
        family = get_fingerprint_family(name)
    except KeyError:
        raise ValueError(name)

    seen = set()
    parameters = []
    for term in terms[1:]:
        try:
            left, right = term.split("=")
        except ValueError:
            raise ValueError("Term %r of type %r must have one and only one '='" %
                             (term, type))
        if left in seen:
            raise ValueError("Duplicate name %r in type %r" % (left, type))
        seen.add(left)
        parameters.append((left, right))

    return family.from_parameters(parameters)
