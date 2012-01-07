from __future__ import absolute_import, with_statement
import unittest2
from cStringIO import StringIO

import chemfp
from chemfp import bitops
try:
    import openbabel
    has_openbabel = True
except ImportError:
    has_openbabel = False

try:
    # I need to import 'oechem' to make sure I load the shared libries
    # XXX Check for license?
    from openeye import oechem
    has_openeye = False
except ImportError:
    has_openeye = False

try:
    from rdkit import Chem
    has_rdkit = True
except ImportError:
    has_rdkit = False

from support import fullpath, PUBCHEM_SDF, PUBCHEM_SDF_GZ


DBL_MIN = 2.2250738585072014e-308 # Assumes 64 bit doubles
assert DBL_MIN > 0.0

CHEBI_TARGETS = fullpath("chebi_rdmaccs.fps")
CHEBI_QUERIES = fullpath("chebi_queries.fps.gz")
MACCS_SMI = fullpath("maccs.smi")

# Backwards compatibility for Python 2.5
try:
    next
except NameError:
    def next(it):
        return it.next()

QUERY_ARENA = next(chemfp.open(CHEBI_QUERIES).iter_arenas(10))
        
class CommonReaderAPI(object):
    _open = None
    
    def _check_target_metadata(self, metadata):
        self.assertEqual(metadata.num_bits, 166)
        self.assertEqual(metadata.num_bytes, 21)
        self.assertEqual(metadata.software, "OEChem/1.7.4 (20100809)")
        self.assertEqual(metadata.type, "RDMACCS-OpenEye/1")
        self.assertEqual(metadata.sources, ["/Users/dalke/databases/ChEBI_lite.sdf.gz"])
        self.assertEqual(metadata.date, "2011-09-16T13:49:04")
        self.assertEqual(metadata.aromaticity, "mmff")

    def _check_query_metadata(self, metadata):
        self.assertEqual(metadata.num_bits, 166)
        self.assertEqual(metadata.num_bytes, 21)
        self.assertEqual(metadata.software, "OEChem/1.7.4 (20100809)")
        self.assertEqual(metadata.type, "RDMACCS-OpenEye/1")
        self.assertEqual(metadata.sources, ["/Users/dalke/databases/ChEBI_lite.sdf.gz"])
        self.assertEqual(metadata.date, "2011-09-16T13:28:43")
        self.assertEqual(metadata.aromaticity, "openeye")
        
    
    def test_uncompressed_open(self):
        reader = self._open(CHEBI_TARGETS)
        self._check_target_metadata(reader.metadata)
        num = sum(1 for x in reader)
        self.assertEqual(num, 2000)

    def test_compressed_open(self):
        reader = self._open(CHEBI_QUERIES)
        self._check_query_metadata(reader.metadata)
        num = sum(1 for x in reader)
        self.assertEqual(num, 154)

    def test_iteration(self):
        assert self.hit_order is not sorted, "not appropriate for sorted arenas"
        reader = iter(self._open(CHEBI_TARGETS))
        fields = [next(reader) for i in range(5)]
        self.assertEqual(fields, 
                         [("CHEBI:776", "00000000000000008200008490892dc00dc4a7d21e".decode("hex")),
                          ("CHEBI:1148", "000000000000200080000002800002040c0482d608".decode("hex")),
                          ("CHEBI:1734", "0000000000000221000800111601017000c1a3d21e".decode("hex")),
                          ("CHEBI:1895", "00000000000000000000020000100000000400951e".decode("hex")),
                          ("CHEBI:2303", "0000000002001021820a00011681015004cdb3d21e".decode("hex"))])

      
    def test_iter_arenas_default_size(self):
        assert self.hit_order is not sorted, "not appropriate for sorted arenas"
        reader = self._open(CHEBI_TARGETS)
        count = 0
        for arena in reader.iter_arenas():
            self._check_target_metadata(arena.metadata)
            if count == 0:
                # Check the values of the first arena
                self.assertEqual(arena.arena_ids[-5:],
                                  ['CHEBI:16316', 'CHEBI:16317', 'CHEBI:16318', 'CHEBI:16319', 'CHEBI:16320'])
                
            self.assertEqual(len(arena), 1000)  # There should be two of these
            count += 1
        self.assertEqual(count, 2)
        self.assertEqual(arena.arena_ids[-5:],
                          ['CHEBI:17578', 'CHEBI:17579', 'CHEBI:17580', 'CHEBI:17581', 'CHEBI:17582'])

    def test_iter_arenas_select_size(self):
        assert self.hit_order is not sorted, "not appropriate for sorted arenas"
        reader = self._open(CHEBI_TARGETS)
        count = 0
        for arena in reader.iter_arenas(100):
            self._check_target_metadata(arena.metadata)
            if count == 0:
                self.assertEqual(arena.arena_ids[-5:],
                                  ['CHEBI:5280', 'CHEBI:5445', 'CHEBI:5706', 'CHEBI:5722', 'CHEBI:5864'])
            self.assertEqual(len(arena), 100)
            count += 1
        self.assertEqual(count, 20)
        self.assertEqual(arena.arena_ids[:5],
                          ['CHEBI:17457', 'CHEBI:17458', 'CHEBI:17459', 'CHEBI:17460', 'CHEBI:17464'])

    def test_read_from_file_object(self):
        f = StringIO("""\
#FPS1
#num-bits=8
F0\tsmall
""")
        reader = self._open(f)
        self.assertEqual(sum(1 for x in reader), 1)
        self.assertEqual(reader.metadata.num_bits, 8)

    def test_read_from_empty_file_object(self):
        f = StringIO("")
        reader = self._open(f)
        self.assertEqual(sum(1 for x in reader), 0)
        self.assertEqual(reader.metadata.num_bits, 0)

    def test_read_from_header_only_file_object(self):
        f = StringIO("""\
#FPS1
#num_bits=100
""")
        reader = self._open(f)
        self.assertEqual(sum(1 for x in reader), 0)
        self.assertEqual(reader.metadata.num_bits, 100)


    #
    # Count tanimoto hits using a fingerprint
    # 

    def test_count_tanimoto_hits_fp_default(self):
        reader = self._open(CHEBI_TARGETS)
        num_hits = reader.count_tanimoto_hits_fp("000000102084322193de9fcfbffbbcfbdf7ffeff1f".decode("hex"))
        self.assertEqual(num_hits, 176)

    def test_count_tanimoto_hits_fp_set_default(self):
        # This is set to the default value
        reader = self._open(CHEBI_TARGETS)
        num_hits = reader.count_tanimoto_hits_fp("000000102084322193de9fcfbffbbcfbdf7ffeff1f".decode("hex"),
                                                 threshold = 0.7)
        self.assertEqual(num_hits, 176)

    def test_count_tanimoto_hits_fp_set_threshold(self):
        reader = self._open(CHEBI_TARGETS)
        num_hits = reader.count_tanimoto_hits_fp("000000102084322193de9fcfbffbbcfbdf7ffeff1f".decode("hex"),
                                                 threshold = 0.8)
        self.assertEqual(num_hits, 108)

    def test_count_tanimoto_hits_fp_set_max_threshold(self):
        reader = self._open(CHEBI_TARGETS)
        num_hits = reader.count_tanimoto_hits_fp("000000102084322193de9fcfbffbbcfbdf7ffeff1f".decode("hex"),
                                                 threshold = 1.0)
        self.assertEqual(num_hits, 1)

    def test_count_tanimoto_hits_fp_set_min_threshold(self):
        reader = self._open(CHEBI_TARGETS)
        num_hits = reader.count_tanimoto_hits_fp("000000102084322193de9fcfbffbbcfbdf7ffeff1f".decode("hex"),
                                                 threshold = DBL_MIN)
        # It isn't 2000 since there are some scores of 0.0
        self.assertEqual(num_hits, 1993)

    def test_count_tanimoto_hits_fp_0(self):
        reader = self._open(CHEBI_TARGETS)
        num_hits = reader.count_tanimoto_hits_fp("000000000000000000000000000000000000000000".decode("hex"),
                                                 threshold = 1./1000)
        self.assertEqual(num_hits, 0)


    def test_count_tanimoto_hits_fp_threshold_range_error(self):
        reader = self._open(CHEBI_TARGETS)
        with self.assertRaisesRegexp(ValueError, "threshold must between 0.0 and 1.0, inclusive") as e:
            for x in reader.count_tanimoto_hits_fp(
                "000000102084322193de9fcfbffbbcfbdf7ffeff1f".decode("hex"),
                threshold = 1.1):
                raise AssertionError("Should not happen!")
        reader = self._open(CHEBI_TARGETS)
        with self.assertRaisesRegexp(ValueError, "threshold must between 0.0 and 1.0, inclusive") as e:
            for x in reader.count_tanimoto_hits_fp(
                "000000102084322193de9fcfbffbbcfbdf7ffeff1f".decode("hex"),
                threshold = -0.00001):
                raise AssertionError("Should not happen")

    #
    # Count tanimoto hits using an arena
    #

    def test_id_count_tanimoto_default(self):
        targets = self._open(CHEBI_TARGETS)
        results = targets.id_count_tanimoto_hits(QUERY_ARENA)
        ids, counts = zip(*results)
        self.assertSequenceEqual(ids, QUERY_ARENA.arena_ids)
        self.assertSequenceEqual(counts, [4, 179, 40, 32, 1, 3, 28, 11, 46, 7])

    def test_id_count_tanimoto_set_default(self):
        targets = self._open(CHEBI_TARGETS)
        results = targets.id_count_tanimoto_hits(QUERY_ARENA, threshold=0.7)
        ids, counts = zip(*results)
        self.assertSequenceEqual(ids, QUERY_ARENA.arena_ids)
        self.assertSequenceEqual(counts, [4, 179, 40, 32, 1, 3, 28, 11, 46, 7])

    def test_id_count_tanimoto_set_threshold(self):
        targets = self._open(CHEBI_TARGETS)
        results = targets.id_count_tanimoto_hits(QUERY_ARENA, threshold=0.9)
        ids, counts = zip(*results)
        self.assertSequenceEqual(ids, QUERY_ARENA.arena_ids)
        self.assertSequenceEqual(counts, [0, 97, 7, 1, 0, 1, 1, 0, 1, 1])

    def test_id_count_tanimoto_hits_threshold_range_error(self):
        reader = self._open(CHEBI_TARGETS)
        with self.assertRaisesRegexp(ValueError, "threshold must between 0.0 and 1.0, inclusive") as e:
            for x in reader.id_count_tanimoto_hits(QUERY_ARENA, threshold = 1.1):
                raise AssertionError("Shouldn't get here")
                                          
        reader = self._open(CHEBI_TARGETS)
        with self.assertRaisesRegexp(ValueError, "threshold must between 0.0 and 1.0, inclusive") as e:
            for x in reader.id_count_tanimoto_hits(QUERY_ARENA, threshold = -0.00001):
                raise AssertionError("Shouldn't get here!")
        
        
    #
    # Threshold tanimoto search using a fingerprint
    # 

    def test_id_threshold_tanimoto_search_fp_default(self):
        reader = self._open(CHEBI_TARGETS)
        hits = reader.id_threshold_tanimoto_search_fp("000000102084322193de9fcfbffbbcfbdf7ffeff1f".decode("hex"))
        self.assertEqual(len(hits), 176)
        first_hits = [('CHEBI:3139', 0.72277227722772275), ('CHEBI:4821', 0.71134020618556704),
                      ('CHEBI:15345', 0.94505494505494503), ('CHEBI:15346', 0.92307692307692313),
                      ('CHEBI:15351', 0.96703296703296704), ('CHEBI:15371', 0.96703296703296704)]
        last_hits = [('CHEBI:17383', 0.72164948453608246), ('CHEBI:17422', 0.73913043478260865),
                     ('CHEBI:17439', 0.81000000000000005), ('CHEBI:17469', 0.72631578947368425),
                     ('CHEBI:17510', 0.70526315789473681), ('CHEBI:17552', 0.71578947368421053)]
        if self.hit_order is not sorted:
            self.assertEqual(hits[:6], first_hits)
            self.assertEqual(hits[-6:], last_hits)
        else:
            for x in first_hits + last_hits:
                self.assertIn(x, hits)


    def test_id_threshold_tanimoto_search_fp_set_default(self):
        # This is set to the default value
        reader = self._open(CHEBI_TARGETS)
        hits = reader.id_threshold_tanimoto_search_fp("000000102084322193de9fcfbffbbcfbdf7ffeff1f".decode("hex"),
                                                   threshold = 0.7)
        self.assertEqual(len(hits), 176)
        first_hits = [('CHEBI:3139', 0.72277227722772275), ('CHEBI:4821', 0.71134020618556704),
                      ('CHEBI:15345', 0.94505494505494503), ('CHEBI:15346', 0.92307692307692313),
                      ('CHEBI:15351', 0.96703296703296704), ('CHEBI:15371', 0.96703296703296704)]
        last_hits = [('CHEBI:17383', 0.72164948453608246), ('CHEBI:17422', 0.73913043478260865),
                     ('CHEBI:17439', 0.81000000000000005), ('CHEBI:17469', 0.72631578947368425),
                     ('CHEBI:17510', 0.70526315789473681), ('CHEBI:17552', 0.71578947368421053)]
        if self.hit_order is not sorted:
            self.assertEqual(hits[:6], first_hits)
            self.assertEqual(hits[-6:], last_hits)
        else:
            for x in first_hits + last_hits:
                self.assertIn(x, hits)

    def test_id_threshold_tanimoto_search_fp_set_threshold(self):
        reader = self._open(CHEBI_TARGETS)
        hits = reader.id_threshold_tanimoto_search_fp("000000102084322193de9fcfbffbbcfbdf7ffeff1f".decode("hex"),
                                                 threshold = 0.8)
        self.assertEqual(len(hits), 108)
        first_hits = [('CHEBI:15345', 0.94505494505494503), ('CHEBI:15346', 0.92307692307692313),
                      ('CHEBI:15351', 0.96703296703296704), ('CHEBI:15371', 0.96703296703296704),
                      ('CHEBI:15380', 0.92391304347826086), ('CHEBI:15448', 0.92391304347826086)]
        last_hits = [('CHEBI:15982', 0.81818181818181823), ('CHEBI:16304', 0.81000000000000005),
                     ('CHEBI:16625', 0.94565217391304346), ('CHEBI:17068', 0.90526315789473688),
                     ('CHEBI:17157', 0.94505494505494503), ('CHEBI:17439', 0.81000000000000005)]
        if self.hit_order is not sorted:
            self.assertEqual(hits[:6], first_hits)
            self.assertEqual(hits[-6:], last_hits)
        else:
            for x in first_hits + last_hits:
                self.assertIn(x, hits)

    def test_id_threshold_tanimoto_search_fp_set_max_threshold(self):
        reader = self._open(CHEBI_TARGETS)
        hits = reader.id_threshold_tanimoto_search_fp("000000102084322193de9fcfbffbbcfbdf7ffeff1f".decode("hex"),
                                                   threshold = 1.0)
        self.assertEqual(hits, [('CHEBI:15523', 1.0)])

    def test_id_threshold_tanimoto_search_fp_set_min_threshold(self):
        reader = self._open(CHEBI_TARGETS)
        hits = reader.id_threshold_tanimoto_search_fp("000000102084322193de9fcfbffbbcfbdf7ffeff1f".decode("hex"),
                                                   threshold = DBL_MIN)
        # It isn't 2000 since there are some scores of 0.0
        self.assertEqual(len(hits), 1993)

    def test_id_threshold_tanimoto_search_fp_0_on_0(self):
        zeros = ("0000\tfirst\n"
                 "0010\tsecond\n"
                 "0000\tthird\n")
        f = StringIO(zeros)
        reader = self._open(f)
        hits = reader.id_threshold_tanimoto_search_fp("0000".decode("hex"), threshold=0.0)
        self.assertEquals(self.hit_order(hits),
                          self.hit_order([ ("first", 0.0), ("second", 0.0), ("third", 0.0) ]))

    def test_id_threshold_tanimoto_search_fp_0(self):
        reader = self._open(CHEBI_TARGETS)
        hits = reader.id_threshold_tanimoto_search_fp("000000000000000000000000000000000000000000".decode("hex"),
                                                   threshold = 1./1000)
        self.assertEqual(hits, [])


    def test_id_threshold_tanimoto_search_fp_threshold_range_error(self):
        reader = self._open(CHEBI_TARGETS)
        with self.assertRaisesRegexp(ValueError, "threshold must between 0.0 and 1.0, inclusive") as e:
            reader.id_threshold_tanimoto_search_fp("000000102084322193de9fcfbffbbcfbdf7ffeff1f".decode("hex"),
                                          threshold = 1.1)
        reader = self._open(CHEBI_TARGETS)
        with self.assertRaisesRegexp(ValueError, "threshold must between 0.0 and 1.0, inclusive") as e:
            reader.id_threshold_tanimoto_search_fp("000000102084322193de9fcfbffbbcfbdf7ffeff1f".decode("hex"),
                                          threshold = -0.00001)

    #
    # Threshold tanimoto search using an arena
    #

    def test_threshold_tanimoto_arena_default(self):
        targets = self._open(CHEBI_TARGETS)
        hits = list(targets.id_threshold_tanimoto_search(QUERY_ARENA))
        self.assertEqual([len(x[1]) for x in hits], [4, 179, 40, 32, 1, 3, 28, 11, 46, 7])
        self.assertEqual(hits[0][1], [('CHEBI:16148', 0.7142857142857143), ('CHEBI:17034', 0.8571428571428571),
                                    ('CHEBI:17302', 0.8571428571428571), ('CHEBI:17539', 0.72222222222222221)])


    def test_threshold_tanimoto_arena_set_default(self):
        targets = self._open(CHEBI_TARGETS)
        result = targets.id_threshold_tanimoto_search(QUERY_ARENA, threshold=0.7)
        ids, hits = zip(*result)
        self.assertSequenceEqual(ids, QUERY_ARENA.arena_ids)
        self.assertEqual(map(len, hits), [4, 179, 40, 32, 1, 3, 28, 11, 46, 7])
        self.assertEqual(self.hit_order(hits[-1]),
                         self.hit_order([('CHEBI:15621', 0.8571428571428571), ('CHEBI:15882', 0.83333333333333337),
                                         ('CHEBI:16008', 0.80000000000000004), ('CHEBI:16193', 0.80000000000000004),
                                         ('CHEBI:16207', 1.0), ('CHEBI:17231', 0.76923076923076927),
                                         ('CHEBI:17450', 0.75)]))


    def test_id_threshold_tanimoto_arena_set_threshold(self):
        targets = self._open(CHEBI_TARGETS)
        result = targets.id_threshold_tanimoto_search(QUERY_ARENA, threshold=0.9)
        ids, hits = zip(*result)
        self.assertSequenceEqual(ids, QUERY_ARENA.arena_ids)
        self.assertEqual(map(len, hits), [0, 97, 7, 1, 0, 1, 1, 0, 1, 1])
        self.assertEqual(self.hit_order(hits[2]),
                         self.hit_order([('CHEBI:15895', 1.0), ('CHEBI:16165', 1.0),
                                         ('CHEBI:16292', 0.93333333333333335), ('CHEBI:16392', 0.93333333333333335),
                                         ('CHEBI:17100', 0.93333333333333335), ('CHEBI:17242', 0.90000000000000002),
                                         ('CHEBI:17464', 1.0)]))

    def test_id_threshold_tanimoto_search_0_on_0(self):
        zeros = ("0000\tfirst\n"
                 "0010\tsecond\n"
                 "0000\tthird\n")
        query_arena = next(chemfp.open(StringIO(zeros)).iter_arenas())
        self.assertEqual(query_arena.ids, ["first", "second", "third"])

        targets = self._open(StringIO(zeros))
        result = targets.id_threshold_tanimoto_search(query_arena, threshold=0.0)
        ids, hits = zip(*result)
        self.assertSequenceEqual(ids, query_arena.arena_ids)
        self.assertEquals(map(len, hits), [3, 3, 3])

        targets = self._open(StringIO(zeros))
        result = targets.id_threshold_tanimoto_search(query_arena, threshold=0.000001)
        ids, hits = zip(*result)
        self.assertSequenceEqual(ids, query_arena.arena_ids)
        self.assertEquals(map(len, hits), [0, 1, 0])
        

    def test_id_threshold_tanimoto_search_threshold_range_error(self):
        reader = self._open(CHEBI_TARGETS)
        with self.assertRaisesRegexp(ValueError, "threshold must between 0.0 and 1.0, inclusive") as e:
            for x in reader.id_threshold_tanimoto_search(QUERY_ARENA, threshold = 1.1):
                raise AssertionError("should never get here")
                                          
        reader = self._open(CHEBI_TARGETS)
        with self.assertRaisesRegexp(ValueError, "threshold must between 0.0 and 1.0, inclusive") as e:
            for x in reader.id_threshold_tanimoto_search(QUERY_ARENA, threshold = -0.00001):
                raise AssertionError("should never get here!")
        
        
    #
    # K-nearest tanimoto search using a fingerprint
    # 

    def test_id_knearest_tanimoto_search_fp_default(self):
        reader = self._open(CHEBI_TARGETS)
        hits = reader.id_knearest_tanimoto_search_fp("00000000100410200290000b03a29241846163ee1f".decode("hex"))
        self.assertEqual(hits, [('CHEBI:8069', 1.0),
                                ('CHEBI:6758', 0.78723404255319152),
                                ('CHEBI:7983', 0.73999999999999999)])

    def test_id_knearest_tanimoto_search_fp_set_default(self):
        # This is set to the default values
        reader = self._open(CHEBI_TARGETS)
        hits = reader.id_knearest_tanimoto_search_fp("000000102084322193de9fcfbffbbcfbdf7ffeff1f".decode("hex"),
                                                     k = 3, threshold = 0.7)
        self.assertEquals(len(hits), 3, hits)
        if hits[1][0] == "CHEBI:15483":
            self.assertEqual(hits, [('CHEBI:15523', 1.0), ('CHEBI:15483', 0.98913043478260865),
                                    ('CHEBI:15480', 0.98913043478260865)])
        else:
            self.assertEqual(hits, [('CHEBI:15523', 1.0), ('CHEBI:15480', 0.98913043478260865),
                                    ('CHEBI:15483', 0.98913043478260865)])
        
    def test_id_knearest_tanimoto_search_fp_set_knearest(self):
        reader = self._open(CHEBI_TARGETS)
        hits = reader.id_knearest_tanimoto_search_fp("000000102084322193de9fcfbffbbcfbdf7ffeff1f".decode("hex"),
                                                 k = 5, threshold = 0.8)
        expected = [('CHEBI:15523', 1.0), ('CHEBI:15483', 0.98913043478260865),
                    ('CHEBI:15480', 0.98913043478260865), ('CHEBI:15478', 0.98901098901098905),
                    ('CHEBI:15486', 0.97802197802197799)]
        if hits[1][0] == "CHEBI:15480" and hits[2][0] == "CHEBI:15483":
            expected[1], expected[2] = expected[2], expected[1]
        self.assertEqual(hits, expected)


    def test_id_knearest_tanimoto_search_fp_set_max_threshold(self):
        reader = self._open(CHEBI_TARGETS)
        hits = reader.id_knearest_tanimoto_search_fp("000000102084322193de9fcfbffbbcfbdf7ffeff1f".decode("hex"),
                                                   threshold = 1.0)
        self.assertEqual(hits, [('CHEBI:15523', 1.0)])

    def test_id_knearest_tanimoto_search_fp_set_knearest_1(self):
        reader = self._open(CHEBI_TARGETS)
        hits = reader.id_knearest_tanimoto_search_fp("000000102084322193de9fcfbffbbcfbdf7ffeff1f".decode("hex"),
                                                   k = 1)
        self.assertEqual(hits, [('CHEBI:15523', 1.0)])

    def test_id_knearest_tanimoto_search_fp_set_knearest_0(self):
        reader = self._open(CHEBI_TARGETS)
        hits = reader.id_knearest_tanimoto_search_fp("000000102084322193de9fcfbffbbcfbdf7ffeff1f".decode("hex"),
                                                   k = 0)
        self.assertEqual(hits, [])

    def test_id_knearest_tanimoto_search_fp_knearest_threshold_range_error(self):
        reader = self._open(CHEBI_TARGETS)
        with self.assertRaisesRegexp(ValueError, "threshold must between 0.0 and 1.0, inclusive"):
            reader.id_knearest_tanimoto_search_fp("000000102084322193de9fcfbffbbcfbdf7ffeff1f".decode("hex"),
                                          threshold = 1.1)
        reader = self._open(CHEBI_TARGETS)
        with self.assertRaisesRegexp(ValueError, "threshold must between 0.0 and 1.0, inclusive"):
            reader.id_knearest_tanimoto_search_fp("000000102084322193de9fcfbffbbcfbdf7ffeff1f".decode("hex"),
                                          threshold = -0.00001)

    def test_id_knearest_tanimoto_search_fp_knearest_k_range_error(self):
        reader = self._open(CHEBI_TARGETS)
        with self.assertRaisesRegexp(ValueError, "k must be non-negative") as e:
            reader.id_knearest_tanimoto_search_fp("000000102084322193de9fcfbffbbcfbdf7ffeff1f".decode("hex"),
                                               k = -1)

    #
    # K-nearest tanimoto search using an arena
    #

    def test_id_knearest_tanimoto_default(self):
        targets = self._open(CHEBI_TARGETS)
        result = targets.id_knearest_tanimoto_search(QUERY_ARENA)
        ids, hits = zip(*result)
        self.assertEqual(map(len, hits), [3, 3, 3, 3, 1, 3, 3, 3, 3, 3])
        first_hits = hits[0]
        if first_hits[0][0] == 'CHEBI:17302':
            self.assertEqual(first_hits, [('CHEBI:17302', 0.8571428571428571),
                                          ('CHEBI:17034', 0.8571428571428571),
                                          ('CHEBI:17539', 0.72222222222222221)])
        else:
            self.assertEqual(first_hits, [('CHEBI:17034', 0.8571428571428571),
                                          ('CHEBI:17302', 0.8571428571428571),
                                          ('CHEBI:17539', 0.72222222222222221)])

    def test_id_knearest_tanimoto_set_default(self):
        targets = self._open(CHEBI_TARGETS)
        result = list(targets.id_knearest_tanimoto_search(QUERY_ARENA, k=3, threshold=0.7))
        ids, hits = zip(*result)
        self.assertSequenceEqual(ids, QUERY_ARENA.arena_ids)
        self.assertEqual(map(len, hits), [3, 3, 3, 3, 1, 3, 3, 3, 3, 3])
        self.assertEqual(hits[-1], [('CHEBI:16207', 1.0), ('CHEBI:15621', 0.8571428571428571),
                                     ('CHEBI:15882', 0.83333333333333337)])


    def test_id_knearest_tanimoto_set_threshold(self):
        targets = self._open(CHEBI_TARGETS)
        result = targets.id_knearest_tanimoto_search(QUERY_ARENA, threshold=0.8)
        ids, hits = zip(*result)
        self.assertSequenceEqual(ids, QUERY_ARENA.arena_ids)
        self.assertEqual(map(len, hits), [2, 3, 3, 3, 1, 1, 3, 3, 3, 3])
        self.assertEqual(hits[6], [('CHEBI:16834', 0.90909090909090906),
                                    ('CHEBI:17061', 0.875),
                                    ('CHEBI:16319', 0.84848484848484851)])

    def test_id_knearest_tanimoto_search_knearest_range_error(self):
        reader = self._open(CHEBI_TARGETS)
        with self.assertRaisesRegexp(ValueError, "threshold must between 0.0 and 1.0, inclusive") as e:
            for x in reader.id_knearest_tanimoto_search(QUERY_ARENA, threshold = 1.1):
                raise AssertionError("What?!")
            
        reader = self._open(CHEBI_TARGETS)
        with self.assertRaisesRegexp(ValueError, "threshold must between 0.0 and 1.0, inclusive") as e:
            for x in reader.id_knearest_tanimoto_search(QUERY_ARENA, threshold = -0.00001):
                raise AssertionError("What2?!")
        
    
class TestFPSReader(unittest2.TestCase, CommonReaderAPI):
    hit_order = staticmethod(lambda x: x)
    _open = staticmethod(chemfp.open)

    def test_row_iteration(self):
        reader = chemfp.open(CHEBI_TARGETS)
        num = sum(1 for x in reader.iter_rows())
        self.assertEqual(num, 2000)
        
        row_reader = chemfp.open(CHEBI_TARGETS).iter_rows()
        fields = [next(row_reader) for i in range(5)]
        self.assertEqual(fields,  [
            ['00000000000000008200008490892dc00dc4a7d21e', 'CHEBI:776'],
            ['000000000000200080000002800002040c0482d608', 'CHEBI:1148'],
            ['0000000000000221000800111601017000c1a3d21e', 'CHEBI:1734'],
            ['00000000000000000000020000100000000400951e', 'CHEBI:1895'],
            ['0000000002001021820a00011681015004cdb3d21e', 'CHEBI:2303']])

    def test_iter_blocks(self):
        reader = chemfp.open(CHEBI_TARGETS)
        line_counts = 0
        has_776 = False
        has_17582 = False
        for block in reader.iter_blocks():
            line_counts += block.count("\n")
            if "00000000000000008200008490892dc00dc4a7d21e\tCHEBI:776" in block:
                has_776 = True
            if "00000000020012008008000104000064844ca2521c\tCHEBI:17582" in block:
                has_17582 = True

        self.assertEqual(line_counts, 2000)
        self.assertTrue(has_776, "Missing CHEBI:776")
        self.assertTrue(has_17582, "Missing CHEBI:17582")

    def test_reiter_open_handle_arena_search(self):
        reader = chemfp.open(CHEBI_TARGETS)
        # The main goal is to prevent people from searching a
        # partially open file.  This reflects an implementation
        # problem; the iterator should be shared across all instances.
        it = iter(reader)
        arena = next(it)
        for method in (reader.id_threshold_tanimoto_search,
                       reader.id_knearest_tanimoto_search):
            with self.assertRaisesRegexp(TypeError, "FPS file is not at the start"):
                for x in method(arena):
                    break

    def test_reiter_open_handle_fp_search(self):
        reader = chemfp.open(CHEBI_TARGETS)
        # The main goal is to prevent people from searching a
        # partially open file.  This reflects an implementation
        # problem; the iterator should be shared across all instances.
        it = iter(reader)
        arena = next(it)
        fp = arena[0][1] # Get the fingerprint term
        
        for method in (reader.id_threshold_tanimoto_search_fp,
                       reader.id_knearest_tanimoto_search_fp):
            with self.assertRaisesRegexp(TypeError, "FPS file is not at the start"):
                for x in method(fp):
                    break
        
        


class TestLoadFingerprints(unittest2.TestCase, CommonReaderAPI):
    hit_order = staticmethod(lambda x: x)
    # Hook to handle the common API
    def _open(self, name):
        return chemfp.load_fingerprints(name, reorder=False)

    def test_slice_ids(self):
        fps = self._open(CHEBI_TARGETS)
        self.assertEquals(fps.ids[4:10], fps[4:10].arena_ids)
        self.assertEquals(fps.ids[5:20][1:5], fps[6:10].arena_ids)

    def test_slice_fingerprints(self):
        fps = self._open(CHEBI_TARGETS)
        self.assertEquals(fps[5:45][0], fps[5])
        self.assertEquals(fps[5:45][0], fps[5])
        self.assertEquals(fps[5:45][3:6][0], fps[8])

    def test_slice_negative(self):
        fps = self._open(CHEBI_TARGETS)
        self.assertEquals(fps[len(fps)-1], fps[-1])
        self.assertEquals(fps.ids[-2:], fps[-2:].arena_ids)
        self.assertEquals(fps.ids[-2:], fps[-2:].arena_ids)
        self.assertEquals(list(fps[-2:]), [fps[-2], fps[-1]])
        self.assertEquals(fps[-5:-2][-1], fps[-3])

    def test_slice_errors(self):
        arena = self._open(CHEBI_TARGETS)
        with self.assertRaisesRegexp(IndexError, "arena fingerprint index out of range"):
            arena[len(arena)]
        with self.assertRaisesRegexp(IndexError, "arena fingerprint index out of range"):
            arena[-len(arena)-1]
        with self.assertRaisesRegexp(IndexError, "arena slice step size must be 1"):
            arena[4:45:2]

    def test_search_in_slice(self):
        fps = self._open(CHEBI_TARGETS)
        for i, (id, fp) in enumerate(fps):
            subarena = fps[i:i+1]
            self.assertEquals(len(subarena), 1)
            self.assertEquals(subarena[0][0], id)
            self.assertEquals(subarena[0][1], fp)
            self.assertEquals(subarena.arena_ids[0], id)

            result = list(subarena.id_threshold_tanimoto_search(subarena))
            query_ids, hits = zip(*result)
            self.assertEquals(len(hits), 1)
            self.assertEquals(hits[0], [(id, 1.0)])
            self.assertEquals(list(hits), [[(id, 1.0)]])

            result = list(subarena.id_knearest_tanimoto_search(subarena))
            query_ids, hits = zip(*result)
            self.assertEquals(len(hits), 1)
            self.assertEquals(hits[0], [(id, 1.0)])
            self.assertEquals(list(hits), [[(id, 1.0)]])

            result = subarena.id_count_tanimoto_hits(subarena)
            query_ids, counts = zip(*result)
            self.assertEquals(len(counts), 1)
            self.assertEquals(counts[0], 1)
            self.assertEquals(list(counts), [1])
        self.assertEquals(i, len(fps)-1)

# Use this to verify the other implementations
from chemfp.slow import SlowFingerprints
class TestSlowFingerprints(unittest2.TestCase, CommonReaderAPI):
    hit_order = staticmethod(lambda x: x)
    def _open(self, name):
        reader = chemfp.open(name)
        return SlowFingerprints(reader.metadata, list(reader))

class TestLoadFingerprintsOrdered(unittest2.TestCase, CommonReaderAPI):
    hit_order = staticmethod(sorted)
    # Hook to handle the common API
    def _open(self, name):
        return chemfp.load_fingerprints(name, reorder=True)

    def test_iteration(self):
        expected = [("CHEBI:776", "00000000000000008200008490892dc00dc4a7d21e".decode("hex")),
                    ("CHEBI:1148", "000000000000200080000002800002040c0482d608".decode("hex")),
                    ("CHEBI:1734", "0000000000000221000800111601017000c1a3d21e".decode("hex")),
                    ("CHEBI:1895", "00000000000000000000020000100000000400951e".decode("hex")),
                    ("CHEBI:2303", "0000000002001021820a00011681015004cdb3d21e".decode("hex"))]
        found = []
        for x in self._open(CHEBI_TARGETS):
            try:
                found.append(expected.index(x))
            except ValueError:
                pass
        self.assertEquals(sorted(found), [0, 1, 2, 3, 4])
        

    def test_arena_is_ordered_by_popcount(self):
        arena = self._open(CHEBI_TARGETS)
        prev = 0
        for id, fp in arena:
            popcount = bitops.byte_popcount(fp)
            self.assertTrue(prev <= popcount, (prev, popcount))
            prev = popcount

    def test_iter_arenas_default_size(self):
        arena = self._open(CHEBI_TARGETS)
        ids = [id for (id, fp) in arena]
        for subarena in arena.iter_arenas():
            self.assertEquals(len(subarena), 1000)
            subids = [id for (id, fp) in subarena]
            self.assertEquals(ids[:1000], subids)
            del ids[:1000]
        self.assertFalse(ids)

    def test_iter_arenas_select_size(self):
        arena = self._open(CHEBI_TARGETS)
        ids = [id for (id, fp) in arena]
        prev = 0
        for subarena in arena.iter_arenas(100):
            self._check_target_metadata(subarena.metadata)
            self.assertEqual(len(subarena), 100)
            subids = []
            for id, fp in subarena:
                subids.append(id)
                popcount = bitops.byte_popcount(fp)
                self.assertTrue(prev <= popcount, (prev, popcount))
                prev = popcount
            
            self.assertEquals(ids[:100], subids)
            del ids[:100]

        self.assertFalse(ids)

        
        

SDF_IDS = ['9425004', '9425009', '9425012', '9425015', '9425018',
           '9425021', '9425030', '9425031', '9425032', '9425033',
           '9425034', '9425035', '9425036', '9425037', '9425040',
           '9425041', '9425042', '9425045', '9425046']

class ReadStructureFingerprints(object):
    def _read_ids(self, *args, **kwargs):
        reader = chemfp.read_structure_fingerprints(*args, **kwargs)
        self.assertEqual(reader.metadata.num_bits, self.num_bits)
        ids = [id for (id, fp) in reader]
        self.assertEqual(len(fp), self.fp_size)
        return ids
        
    def test_read_simple(self):
        ids = self._read_ids(self.type, source=PUBCHEM_SDF)
        self.assertEqual(ids, SDF_IDS)

    def test_read_simple_compressed(self):
        ids = self._read_ids(self.type, source=PUBCHEM_SDF_GZ)
        self.assertEqual(ids, SDF_IDS)

    def test_read_missing_filename(self):
        with self.assertRaises(IOError):
            self._read_ids(self.type, "this_file_does_not_exist.sdf")

    def test_read_metadata(self):
        metadata = chemfp.Metadata(type=self.type)
        ids = self._read_ids(metadata, source=PUBCHEM_SDF_GZ)
        self.assertEqual(ids, SDF_IDS)

    def test_read_sdf_gz(self):
        ids = self._read_ids(self.type, source=PUBCHEM_SDF_GZ, format="sdf.gz")
        self.assertEqual(ids, SDF_IDS)

    def test_read_sdf(self):
        ids = self._read_ids(self.type, source=PUBCHEM_SDF, format="sdf")
        self.assertEqual(ids, SDF_IDS)

    def test_read_bad_format(self):
        with self.assertRaisesRegexp(ValueError, "Unknown structure format 'xyzzy'"):
            self._read_ids(self.type, source=PUBCHEM_SDF, format="xyzzy")

    def test_read_bad_compression(self):
        with self.assertRaisesRegexp(ValueError, "Unsupported compression in format 'sdf.Z'"):
            self._read_ids(self.type, source=PUBCHEM_SDF, format="sdf.Z")
        

    def test_read_id_tag(self):
        ids = self._read_ids(self.type, source=PUBCHEM_SDF, id_tag = "PUBCHEM_MOLECULAR_FORMULA")
        self.assertEqual(ids, ["C16H16ClFN4O2", "C18H20N6O3", "C14H19N5O3", "C23H24N4O3", 
                                "C18H23N5O3S", "C19H21ClN4O4", "C18H31N6O4S+", "C18H30N6O4S",
                                "C16H20N4O2", "C19H21N5O3S", "C18H22N4O2", "C18H20ClN5O3",
                                "C16H20N8O2", "C15H17ClN6O3", "C19H21N5O4", "C17H19N5O4",
                                "C17H19N5O4", "C19H23N5O2S", "C15H17BrN4O3"])

# I decided to not check this. The failure is that you'll get a "can't find id" error. Oh well.
#    def test_read_invalid_id_tag(self):
#        self._read_ids(self.type, PUBCHEM_SDF, id_tag = "This\tis\ninvalid>")

    def test_read_smiles(self):
        # Need at least one test with some other format
        ids = self._read_ids(self.type, source=MACCS_SMI)
        self.assertEqual(ids, ["3->bit_2", "4->bit_3", "5->bit_4", "6->bit_5", 
                                "10->bit_9", "11->bit_10", "17->bit_16"] )

    def test_read_unknown_format(self):
        # XXX Fix this - figure out the right way to handle filename-extension/format-option
        with self.assertRaisesRegexp(ValueError, "Unknown structure (format|filename extension).*should_be_sdf_but_is_not"):
            self._read_ids(self.type, fullpath("pubchem.should_be_sdf_but_is_not"))

    def test_read_known_format(self):
        ids = self._read_ids(self.type, fullpath("pubchem.should_be_sdf_but_is_not"), "sdf")
        self.assertEqual(ids, SDF_IDS)

    def test_read_errors(self):
        with self.assertRaisesRegexp(chemfp.ParseError, "Missing title for record #1 .*missing_title.sdf"):
            self._read_ids(self.type, fullpath("missing_title.sdf"))

    def test_read_errors_strict(self):
        with self.assertRaisesRegexp(chemfp.ParseError, "Missing title for record #1 .*missing_title.sdf"):
            self._read_ids(self.type, fullpath("missing_title.sdf"), errors="strict")

    def test_read_errors_ignore(self):
        ids = self._read_ids(self.type, fullpath("missing_title.sdf"), errors="ignore")
        self.assertEqual(ids, ["Good"])

    def test_read_errors_report(self):
        import sys
        from cStringIO import StringIO
        old_stderr = sys.stderr
        sys.stderr = new_stderr = StringIO()
        try:
            ids = self._read_ids(self.type, fullpath("missing_title.sdf"), errors="report")
        finally:
            sys.stderr = old_stderr
            errmsg = new_stderr.getvalue()
            
        self.assertEqual(ids, ["Good"])
        self.assertIn("ERROR: Missing title for record #1", errmsg)
        self.assertNotIn("record #2", errmsg)
        self.assertIn("ERROR: Missing title for record #3", errmsg)
        self.assertIn("Skipping.\n", errmsg)

    def test_read_errors_wrong_setting(self):
        with self.assertRaisesRegexp(ValueError, "'errors' must be one of ignore, report, strict"):
            self._read_ids(self.type, PUBCHEM_SDF, errors="this-is-not.a.valid! setting")

        
# Test classes for the different toolkits

class TestOpenBabelReadStructureFingerprints(unittest2.TestCase, ReadStructureFingerprints):
    type = "OpenBabel-FP2/1"
    num_bits = 1021
    fp_size = 128

TestOpenBabelReadStructureFingerprints = (
  unittest2.skipUnless(has_openbabel, "Open Babel not available")(TestOpenBabelReadStructureFingerprints)
)

class TestOpenEyeReadStructureFingerprints(unittest2.TestCase, ReadStructureFingerprints):
    type = "OpenEye-Path/1"
    num_bits = 1024
    fp_size = 128

TestOpenEyeReadStructureFingerprints = (
  unittest2.skipUnless(has_openeye, "OpenEye not available")(TestOpenEyeReadStructureFingerprints)
)

class TestRDKitReadStructureFingerprints(unittest2.TestCase, ReadStructureFingerprints):
    type = "RDKit-Fingerprint/1"
    num_bits = 2048
    fp_size = 256

TestRDKitReadStructureFingerprints = (
  unittest2.skipUnless(has_rdkit, "RDKit not available")(TestRDKitReadStructureFingerprints)
)

class TestBitOps(unittest2.TestCase):
    def test_byte_union(self):
        for (fp1, fp2, expected) in (
            ("ABC", "ABC", "ABC"),
            ("ABC", "BBC", "CBC"),
            ("BA", "12", "ss")):
            self.assertEquals(bitops.byte_union(fp1, fp2), expected)

    def test_byte_intersect(self):
        for (fp1, fp2, expected) in (
            ("ABC", "ABC", "ABC"),
            ("ABC", "BBC", "@BC"),
            ("AB", "12", "\1\2"),
            ("BA", "12", "\0\0")):
            self.assertEquals(bitops.byte_intersect(fp1, fp2), expected)

    def test_byte_difference(self):
        for (fp1, fp2, expected) in (
            ("A", "C", "\2"),
            ("ABC", "ABC", "\0\0\0"),
            ("ABC", "BBC", "\3\0\0"),
            ("BA", "12", "ss")):
            self.assertEquals(bitops.byte_difference(fp1, fp2), expected)
        
    def test_empty(self):
        self.assertEquals(bitops.byte_union("", ""), "")
        self.assertEquals(bitops.byte_intersect("", ""), "")
        self.assertEquals(bitops.byte_difference("", ""), "")
        
    def test_failures(self):
        for func in (bitops.byte_union,
                     bitops.byte_intersect,
                     bitops.byte_difference):
            with self.assertRaisesRegexp(ValueError, "byte fingerprints must have the same length"):
                func("1", "12")
    

if __name__ == "__main__":
    unittest2.main()

