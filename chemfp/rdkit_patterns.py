from __future__ import absolute_import

from rdkit import Chem

from . import pattern_fingerprinter
from . import rdkit
from . import types
from . import __version__ as chemfp_version

SOFTWARE = rdkit.SOFTWARE + (" chemfp/%s" % (chemfp_version,))

class HydrogenMatcher(object):
    def has_match(self, mol):
        for atom in mol.GetAtoms():
            if atom.GetAtomicNum() == 1:
                return 1
            if atom.GetTotalNumHs():
                return 1
        return 0

    def num_matches(self, mol, largest_count):
        num_hydrogens = 0
        for atom in mol.GetAtoms():
            if atom.GetAtomicNum() == 1:
                num_hydrogens += 1
            num_hydrogens += atom.GetTotalNumHs()
            if num_hydrogens >= largest_count:
                return num_hydrogens
        return num_hydrogens
        
            

class AromaticRings(object):
    def __init__(self):
        # The single ring case is easy; if there's an aromatic atom in a ring
        # then there's a ring
        self._single_matcher = Chem.MolFromSmarts("[aR]")

    def has_match(self, mol):
        return mol.HasSubstructMatch(self._single_matcher)

    def num_matches(self, mol, largest_count):
        nArom = 0
        for ring in mol.GetRingInfo().BondRings():
            if all(mol.GetBondWithIdx(bondIdx).GetIsAromatic() for bondIdx in ring):
                nArom += 1
                if nArom == largest_count:
                    return nArom
        return nArom

def _is_hetereo_aromatic_atom(atom):
    return atom.GetIsAromatic() and atom.GetAtomicNum() not in (1, 6)

class HeteroAromaticRings(object):
    def __init__(self):
        # In the single match case, if there's an aromatic non-carbon atom
        # then it's a hetereo ring
        self._single_matcher = Chem.MolFromSmarts("[aR;!#6]")

    def has_match(self, mol):
        return mol.HasSubstructMatch(self._single_matcher)

    def num_matches(self, mol, largest_count):
        nArom = 0
        for ring in mol.GetRingInfo().AtomRings():
            if any(_is_hetereo_aromatic_atom(mol.GetAtomWithIdx(atomIdx))
                                 for atomIdx in ring):
                nArom += 1
                if nArom == largest_count:
                    return nArom
        return nArom


class NumFragments(object):
    def has_match(self, mol):
        return mol.GetNumAtoms() > 0
    def num_matches(self, mol, largest_count):
        return len(Chem.GetMolFrags(mol))

# RDKit matches "molecule.HasSubstructMatch(match_pattern)"
# while every other toolkit does something like "match_pattern.HasSubstructMatch(molecule)"
# Since SMARTS doesn't handle all the pattern cases, I prefer the second ordering.
# This class inverts the order so I can do that.
class InvertedMatcher(object):
    def __init__(self, matcher):
        self.matcher = matcher
    def has_match(self, mol):
        return mol.HasSubstructMatch(self.matcher)
    def num_matches(self, mol, max_count):
        return len(mol.GetSubstructMatches(self.matcher))

_pattern_classes = {
    "<H>": HydrogenMatcher,
    "<aromatic-rings>": AromaticRings,
    "<hetero-aromatic-rings>": HeteroAromaticRings,
    "<fragments>": NumFragments,
    }
    

def rdkit_compile_pattern(pattern, max_count):
    if pattern in _pattern_classes:
        return _pattern_classes[pattern]()
    
    elif pattern.startswith("<"):
        raise NotImplementedError(pattern)
        #return NotImplemented

    # Everything else must be a SMARTS pattern

    matcher = Chem.MolFromSmarts(pattern)
    if matcher is None:
        raise pattern_fingerprinter.UnsupportedPatternError(
            pattern, "Can not interpret SMARTS pattern")
    return InvertedMatcher(matcher)

class RDKitPatternFingerprinter(pattern_fingerprinter.PatternFingerprinter):
    def __init__(self, patterns):
        assert patterns is not None
        super(RDKitPatternFingerprinter, self).__init__(patterns, rdkit_compile_pattern)
        
    def fingerprint(self, mol):
        bytes = [0] * self.num_bytes
        for matcher, largest_count, count_info_tuple in self.matcher_definitions:
            if largest_count == 1:
                if matcher.has_match(mol):
                    count_info = count_info_tuple[0]
                    bytes[count_info.byteno] |= count_info.bitmask
            else:
                actual_count = matcher.num_matches(mol, largest_count)
                if actual_count:
                    for count_info in count_info_tuple:
                        if actual_count >= count_info.count:
                            bytes[count_info.byteno] |= count_info.bitmask
                        else:
                            break
        return "".join(map(chr, bytes))

class _CachedFingerprinters(dict):
    def __missing__(self, name):
        patterns = pattern_fingerprinter._load_named_patterns(name)
        fingerprinter = RDKitPatternFingerprinter(patterns)
        self[name] = fingerprinter
        return fingerprinter
_cached_fingerprinters = _CachedFingerprinters()



_base = rdkit._base.clone(
    software = SOFTWARE)

SubstructRDKitFingerprinter_v1 = _base.clone(
    name = "ChemFP-Substruct-RDKit/1",
    num_bits = 881,
    make_fingerprinter = lambda: _cached_fingerprinters["substruct"].fingerprint)


#    def describe(self, bitno):
#        return self._fingerprinter.describe(bitno)

RDMACCSRDKitFingerprinter_v1 = _base.clone(
    name = "RDMACCS-RDKit/1",
    num_bits = 166,
    make_fingerprinter = lambda: _cached_fingerprinters["rdmaccs"].fingerprint)
