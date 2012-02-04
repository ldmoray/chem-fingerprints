# Internal module to help with FPS-based searches
from __future__ import absolute_import

import ctypes
import itertools
import array

import _chemfp
from . import ChemFPError
from . import check_fp_problems, check_metadata_problems

class FPSFormatError(ChemFPError):
    def __init__(self, code, filename, lineno):
        self.code = code
        self.filename = filename
        self.lineno = lineno
        super(FPSFormatError, self).__init__(code, filename, lineno)
    def __repr__(self):
        return "FPSFormatError(%r, %r, %r)" % (self.code, self.filename, self.lineno)
    def __str__(self):
        return "%s at line %s of %r" % (_chemfp.strerror(self.code), self.lineno, self.filename)

def _chemfp_error(err, lineno, filename):
    if -40 <= err <= -30:
        return FPSFormatError(err, filename, lineno)
    elif err == -2:
        raise MemoryError(_chemfp.strerror(err))
    else:
        # This shouldn't happen
        return RuntimeError(_chemfp.strerror(err))

def require_matching_sizes(query_arena, target_reader):
    query_num_bits = query_arena.metadata.num_bits
    assert query_num_bits is not None, "arenas must define num_bits"
    target_num_bits = target_reader.metadata.num_bits
    if (target_num_bits is not None):
        if query_num_bits != target_num_bits:
            raise ValueError("query_arena has %d bits while target_reader has %d bits" % (query_num_bits, target_num_bits))

    query_num_bytes = query_arena.metadata.num_bytes
    assert query_num_bytes is not None, "arenas must define num_bytes"
    target_num_bytes = target_reader.metadata.num_bytes
    if target_num_bytes is None:
        raise ValueError("target_reader missing num_bytes metadata")
    if query_num_bytes != target_num_bytes:
        raise ValueError("query_arena uses %d bytes while target_reader uses %d bytes" % (query_num_bytes, target_num_bytes))


def report_errors(problem_report):
    for (severity, error, msg_template) in problem_report:
        if severity == "error":
            raise TypeError(msg_template % dict(metadata1 = "query",
                                                metadata2 = "target"))

######## count Tanimoto search #########

def _fp_to_arena(query_fp, metadata):
    assert len(query_fp) == metadata.num_bytes
    from . import arena
    return arena.FingerprintArena(metadata, 1, 0, 0, len(query_fp), query_fp, "", [None])

def count_tanimoto_hits_fp(query_fp, target_reader, threshold):
    return count_tanimoto_hits_arena(_fp_to_arena(query_fp, target_reader.metadata), target_reader, threshold)[0]

def count_tanimoto_hits_arena(query_arena, target_reader, threshold):
    require_matching_sizes(query_arena, target_reader)
    counts = array.array("i", (0 for i in xrange(len(query_arena))))

    lineno = target_reader._first_fp_lineno

    for block in target_reader.iter_blocks():
        err, num_lines = _chemfp.fps_count_tanimoto_hits(
            query_arena.metadata.num_bits,
            query_arena.start_padding, query_arena.end_padding,
            query_arena.storage_size, query_arena.arena, 0, -1,
            block, 0, -1,
            threshold, counts)
        lineno += num_lines
        if err:
            raise _chemfp_error(err, lineno, target_reader._filename)

    return list(counts)
    



######## threshold Tanimoto search #########

class TanimotoCell(ctypes.Structure):
    _fields_ = [("score", ctypes.c_double),
                ("query_index", ctypes.c_int),
                ("id_start", ctypes.c_int),
                ("id_end", ctypes.c_int)]


def threshold_tanimoto_search_fp(query_fp, target_reader, threshold):
    """Find matches in the target reader which are at least threshold similar to the query fingerprint

    The results is an FPSSearchResults instance contain the result.
    """
    ids = []
    scores = []
    fp_size = len(query_fp)
    num_bits = fp_size * 8
        
    NUM_CELLS = 1000
    cells = (TanimotoCell*NUM_CELLS)()

    lineno = target_reader._first_fp_lineno
    
    for block in target_reader.iter_blocks():
        start = 0
        end = len(block)
        while 1:
            err, start, num_lines, num_cells = _chemfp.fps_threshold_tanimoto_search(
                num_bits, 0, 0, fp_size, query_fp, 0, -1,
                block, start, end,
                threshold, cells)
            lineno += num_lines
            if err:
                raise _chemfp_error(err, lineno, target_reader._filename)
                
            for cell in itertools.islice(cells, 0, num_cells):
                    ids.append(block[cell.id_start:cell.id_end])
                    scores.append(cell.score)
            if start == end:
                break
    return FPSSearchResult(ids, scores)

def threshold_tanimoto_search_arena(query_arena, target_reader, threshold):
    """Find matches in the target reader which are at least threshold similar to the query arena fingerprints

    The results are a list in the form [search_results1, search_results2, ...]
    where search_results are in the same order as the fingerprints in the query_arena.
    """
    
    require_matching_sizes(query_arena, target_reader)

    if not query_arena:
        return FPSSearchResults([])
    results = [FPSSearchResult([], []) for i in xrange(len(query_arena))]
    
    # Compute at least 100 tanimotos per query, but at most 10,000 at a time
    # (That's about 200K of memory)
    NUM_CELLS = max(10000, len(query_arena) * 100)
    cells = (TanimotoCell*NUM_CELLS)()

    lineno = target_reader._first_fp_lineno

    for block in target_reader.iter_blocks():
        start = 0
        end = len(block)
        while 1:
            err, start, num_lines, num_cells = _chemfp.fps_threshold_tanimoto_search(
                query_arena.metadata.num_bits,
                query_arena.start_padding, query_arena.end_padding,
                query_arena.storage_size, query_arena.arena, 0, -1,
                block, start, end,
                threshold, cells)
            lineno += num_lines
            if err:
                raise _chemfp_error(err, lineno, target_reader._filename)
                
            for cell in itertools.islice(cells, 0, num_cells):
                id = block[cell.id_start:cell.id_end]
                result = results[cell.query_index]
                result.ids.append(id)
                result.scores.append(cell.score)
                
            if start == end:
                break

    return FPSSearchResults(results)
            
######### k-nearest Tanimoto search, with threshold


# Support for peering into the chemfp_fps_heap data structure

def _make_knearest_search(num_queries, k):
    class TanimotoHeap(ctypes.Structure):
        _fields_ = [("size", ctypes.c_int),
                    ("heap_state", ctypes.c_int),
                    ("indices", ctypes.POINTER(ctypes.c_int*k)),
                    ("ids", ctypes.POINTER(ctypes.c_char_p*k)),
                    ("scores", ctypes.POINTER(ctypes.c_double*k))]

    class KNearestSearch(ctypes.Structure):
        _fields_ = [("queries_start", ctypes.c_char_p),
                    ("num_queries", ctypes.c_int),
                    ("query_fp_size", ctypes.c_int),
                    ("query_storage_size", ctypes.c_int),
                    ("k", ctypes.c_int),
                    ("search_state", ctypes.c_int),
                    ("threshold", ctypes.c_double),
                    ("heaps", ctypes.POINTER(TanimotoHeap*num_queries)),
                    ("num_targets_processed", ctypes.c_int),
                    ("_all_ids", ctypes.c_void_p),
                    ("_all_scores", ctypes.c_void_p)]

    return KNearestSearch()


def knearest_tanimoto_search_fp(query_fp, target_reader, k, threshold):
    """Find k matches in the target reader which are at least threshold similar to the query fingerprint

    The results is an FPSSearchResults instance contain the result.
    """
    query_arena = _fp_to_arena(query_fp, target_reader.metadata)
    return knearest_tanimoto_search_arena(query_arena, target_reader, k, threshold)[0]

def knearest_tanimoto_search_arena(query_arena, target_reader, k, threshold):
    require_matching_sizes(query_arena, target_reader)
    if k < 0:
        raise ValueError("k must be non-negative")

    num_queries = len(query_arena)
    search = _make_knearest_search(num_queries, k)

    _chemfp.fps_knearest_search_init(
        search,
        query_arena.metadata.num_bits,
        query_arena.start_padding, query_arena.end_padding,
        query_arena.storage_size, query_arena.arena, 0, -1,
        k, threshold)

    try:
        for block in target_reader.iter_blocks():
            err = _chemfp.fps_knearest_tanimoto_search_feed(search, block, 0, -1)
            if err:
                lineno = target_reader._first_fp_lineno + search.num_targets_processed
                raise _chemfp_error(err, lineno, target_reader._filename)

        _chemfp.fps_knearest_search_finish(search)

        results = []
        for query_index in xrange(num_queries):
            heap = search.heaps[0][query_index]
            ids = []
            for i in xrange(heap.size):
                id = ctypes.string_at(heap.ids[0][i])
                ids.append(id)
            scores = heap.scores[0][:heap.size]
            results.append(FPSSearchResult(ids, scores))
        return FPSSearchResults(results)

    finally:
        _chemfp.fps_knearest_search_free(search)

def _reorder_row(ids, scores, name):
    indices = range(len(ids))
    if name == "decreasing-score":
        indices.sort(key=lambda i: (-scores[i], ids[i]))
    elif name == "increasing-score":
        indices.sort(key=lambda i: (scores[i], ids[i]))
    elif name == "decreasing-id":
        indices.sort(key=lambda i: ids[i], reverse=True)
    elif name == "increasing-id":
        indices.sort(key=lambda i: ids[i])
    elif name == "reverse":
        ids.reverse()
        scores.reverse()
        return
    elif name == "move-closest-first":
        if len(ids) <= 1:
            # Short-circuit when I don't need to do anything
            return
        x = max(scores)
        i = scores.index(x)
        ids[0], ids[i] = ids[i], ids[0]
        scores[0], scores[i] = scores[i], scores[0]
        return
    else:
        raise ValueError("Unknown sort order")

    new_ids = [ids[i] for i in indices]
    new_scores = [scores[i] for i in indices]
    ids[:] = new_ids
    scores[:] = new_scores

class FPSSearchResult(object):
    def __init__(self, ids, scores):
        self.ids = ids
        self.scores = scores
    def __len__(self):
        return len(self.ids)
    def __nonzero__(self):
        return bool(self.ids)
    def __iter__(self):
        return itertools.izip(self.ids, self.scores)
    def __getitem__(self, i):
        return (self.ids[i], self.scores[i])
    def clear(self):
        self.ids = []
        self.scores = []

    def get_ids(self):
        return self.ids
    def get_scores(self):
        return self.scores
    def get_ids_and_scores(self):
        return zip(self.ids, self.scores)
    def reorder(self, order="decreasing-score"):
        _reorder_row(self.ids, self.scores, order)

class FPSSearchResults(object):
    def __init__(self, results):
        self._results = results

    def __len__(self):
        return len(self._results)

    def __getitem__(self, i):
        return self._results[i]

    def __iter__(self):
        return iter(self._results)

    def iter_ids(self):
        for result in self._results:
            yield result.ids

    def iter_scores(self):
        for result in self._results:
            yield result.scores
            
    def iter_ids_and_scores(self):
        for result in self._results:
            yield zip(result.ids, result.scores)

    def reorder_all(self, order="decreasing-score"):
        for result in self._results:
            _reorder_row(result.ids, result.scores, order)

    def clear_all(self):
        for result in self._results:
            result.clear()
