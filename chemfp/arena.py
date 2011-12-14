"""Algorithms and data structure for working with a FingerprintArena.

NOTE: This module should not be used directly.

A FingerprintArena stores the fingerprints as a contiguous byte
string, called the `arena`. Each fingerprint takes `storage_size`
bytes, which may be larger than `num_bytes` if the fingerprints have a
specific memory alignment. The bytes for fingerprint i are
  arena[i*storage_size:i*storage_size+num_bytes]
Additional bytes must contain NUL bytes.

The lookup for `ids[i]` contains the id for fingerprint `i`.

A FingerprintArena has an optional `indices` attribute. When
available, it means that the arena fingerprints and corresponding ids
are ordered by population count, and the fingerprints with popcount
`p` start at index indices[p] and end just before indices[p+1].

"""

from __future__ import absolute_import

import ctypes
from cStringIO import StringIO
import array

from chemfp import FingerprintReader, check_fp_problems, check_metadata_problems
import _chemfp
from chemfp import bitops, search

__all__ = []
    

class FingerprintArena(FingerprintReader):
    """Stores fingerprints in a contiguous block of memory

    The public attributes are:
       metadata
           `Metadata` about the fingerprints
       ids
           list of identifiers, ordered by position
    """
    def __init__(self, metadata, alignment,
                 start_padding, end_padding, storage_size, arena,
                 popcount_indices, ids, start=0, end=None):
        if metadata.num_bits is None:
            raise TypeError("Missing metadata num_bits information")
        if metadata.num_bytes is None:
            raise TypeError("Missing metadata num_bytes information")
        self.metadata = metadata
        self.alignment = alignment
        self.num_bits = metadata.num_bits
        self.start_padding = start_padding
        self.end_padding = end_padding
        self.storage_size = storage_size
        self.arena = arena
        self.popcount_indices = popcount_indices
        self.ids = ids
        self.start = start
        if end is None:
            if self.metadata.num_bytes:
                end = (len(arena) - start_padding - end_padding) // self.storage_size
            else:
                end = 0
        self.end = end
        assert end >= start
        self._range_check = xrange(end-start)

    def __len__(self):
        """Number of fingerprint records in the FingerprintArena"""
        return self.end - self.start

    @property
    def arena_ids(self):
        return self.ids[self.start:self.end]

    def __getitem__(self, i):
        """Return the (id, fingerprint) at position i"""
        if isinstance(i, slice):
            start, end, step = i.indices(self.end - self.start)
            if start >= end:
                return FingerprintArena(self.metadata, self.alignment,
                                        0, 0, self.storage_size, "",
                                        "", [], 0, 0)
            if step != 1:
                raise IndexError("arena slice step size must be 1")
            return FingerprintArena(self.metadata, self.alignment,
                                    self.start_padding, self.end_padding,
                                    self.storage_size, self.arena,
                                    self.popcount_indices, self.ids,
                                    self.start+start, self.start+end)
        try:
            i = self._range_check[i]
        except IndexError:
            raise IndexError("arena fingerprint index out of range")
        arena_i = i + self.start
        start_offset = arena_i * self.storage_size + self.start_padding
        end_offset = start_offset + self.metadata.num_bytes
        return self.ids[arena_i], self.arena[start_offset:end_offset]


    def save(self, destination):
        """Save the arena contents to the given filename or file object"""
        from . import io
        need_close = False
        if isinstance(destination, basestring):
            need_close = True
            output = io.open_output(destination)
        else:
            output = destination

        try:
            io.write_fps1_magic(output)
            io.write_fps1_header(output, self.metadata)
            for id, fp in self:
                io.write_fps1_fingerprint(output, fp, id)
        finally:
            if need_close:
                output.close()
                
    def reset(self):
        """This method is not documented"""
        pass

    def __iter__(self):
        """Iterate over the (id, fingerprint) contents of the arena"""
        storage_size = self.storage_size
        if not storage_size:
            return
        target_fp_size = self.metadata.num_bytes
        arena = self.arena
        for id, start_offset in zip(self.ids[self.start:self.end],
                                    xrange(self.start*storage_size+self.start_padding,
                                           self.end*storage_size+self.start_padding,
                                           storage_size)):
            yield id, arena[start_offset:start_offset+target_fp_size]

    def iter_arenas(self, arena_size = 1000):
        """iterate through `arena_size` fingerprints at a time

        This iterates through the fingerprints `arena_size` at a time,
        yielding a FingerprintArena for each group. Working with
        arenas is often faster than processing one fingerprint at a
        time, and more memory efficient than processing all
        fingerprints at once.

        If arena_size=None then this makes an iterator containing
        a single arena containing all of the input.
        
        :param arena_size: The number of fingerprints to put into an arena.
        :type arena_size: positive integer, or None
        """
        if arena_size is None:
            yield self
            return
        
        storage_size = self.storage_size
        start = self.start
        for i in xrange(0, len(self), arena_size):
            end = start+arena_size
            if end > len(self):
                end = len(self)
            yield FingerprintArena(self.metadata, self.alignment,
                                   self.start_padding, self.end_padding,
                                   self.storage_size, self.arena,
                                   self.popcount_indices, self.ids, start, end)
            start = end

    def count_tanimoto_hits_fp(self, query_fp, threshold=0.7):
        """Count the fingerprints which are similar enough to the query fingerprint

        XXX
        
        Return the number of fingerprints in this arena which are
        at least `threshold` similar to the query fingerprint `query_fp`.

        :param query_fp: query fingerprint
        :type query_fp: byte string
        :param threshold: minimum similarity threshold (default: 0.7)
        :type threshold: float between 0.0 and 1.0, inclusive
        :returns: integer count
        """
        return search.count_tanimoto_hits_fp(query_fp, self, threshold)

    def batch_count_tanimoto_hits(self, queries, threshold=0.7, arena_size=100):
        """Count the fingerprints which are similar enough to each query fingerprint

        XXX
        
        Returns an iterator containing the (query_id, count) for each
        fingerprint in `queries`, where `query_id` is the query
        fingerprint id and `count` is the number of fingerprints found
        which are at least `threshold` similar to the query.

        The order of results is the same as the order of the
        queries. For efficiency reasons, `arena_size` queries are
        processed at a time.
        
        :param queries: query fingerprints
        :type query_fp: FingerprintArena or FPSReader (must implement iter_arenas())
        :param threshold: minimum similarity threshold (default: 0.7)
        :type threshold: float between 0.0 and 1.0, inclusive
        :param arena_size: number of queries to process at a time (default: 100)
        :type arena_size: positive integer
        :returns: list of (query_id, integer count) pairs, one for each query
        """
        for query_arena in queries.iter_arenas(arena_size):            
            result = search.count_tanimoto_hits(query_arena, self, threshold)
            for (query_id, count) in zip(query_arena.arena_ids, result):
                yield query_id, count

    def threshold_tanimoto_search_fp_return_ids(self, query_fp, threshold=0.7):
        """Find the fingerprints which are similar enough to the query fingerprint

        XXX

        Find all of the fingerprints in this arena which are at least
        `threshold` similar to the query fingerprint `query_fp`.
        The hits are returned as a list containing (id, score) tuples
        in arbitrary order.
        
        :param query_fp: query fingerprint
        :type query_fp: byte string
        :param threshold: minimum similarity threshold (default: 0.7)
        :type threshold: float between 0.0 and 1.0, inclusive
        :returns: list of (int, score) tuples
        """
        result = search.threshold_tanimoto_search_fp(query_fp, self, threshold)
        return [(self.ids[index], score) for (index, score) in result]

    def batch_threshold_tanimoto_search_return_ids(self, queries, threshold=0.7,
                                                   arena_size=100):
        """Find the fingerprints which are similar to each of the query fingerprints

        XXX

        For each fingerprint in the `query_arena`, find all of the
        fingerprints in this arena which are at least `threshold`
        similar. The hits are returned as a `SearchResults` instance.
        
        :param query_arena: query arena
        :type query_arena: FingerprintArena
        :param threshold: minimum similarity threshold (default: 0.7)
        :type threshold: float between 0.0 and 1.0, inclusive
        :returns: SearchResults
        """
        for query_arena in queries.iter_arenas(arena_size):
            result = search.threshold_tanimoto_search(query_arena, self, threshold)
            for (query_id, hits) in zip(query_arena.arena_ids, result.iter_ids_and_scores()):
                yield query_id, hits

    def knearest_tanimoto_search_fp_return_ids(self, query_fp, k=3, threshold=0.7):
        """Find the k-nearest fingerprints which are similar to the query fingerprint

        XXX
        
        Find the `k` fingerprints in this arena which are most similar
        to the query fingerprint `query_fp` and which are at least `threshold`
        similar to the query. The hits are returned as a list of
        (id, score) tuples sorted with the highest similarity first.
        Ties are broken arbitrarily.

        :param query_fp: query fingerpring
        :type query_fp: byte string
        :param k: number of nearest neighbors to find (default: 3)
        :type k: positive integer
        :param threshold: minimum similarity threshold (default: 0.7)
        :type threshold: float between 0.0 and 1.0, inclusive
        :returns: SearchResults
        """
        result = search.knearest_tanimoto_search_fp(query_fp, self, k, threshold)
        return [(self.ids[index], score) for (index, score) in result]

    def batch_knearest_tanimoto_search_return_ids(self, query_arena, k=3, threshold=0.7):
        """Find the k-nearest fingerprint which are similar to each of the query fingerprints

        XXX

        For each fingerprint in the `query_arena`, find the `k`
        fingerprints in this arena which are most similar and which
        are at least `threshold` similar to the query fingerprint.
        The hits are returned as a SearchResult where the hits are
        sorted with the highest similarity first. Ties are broken
        arbitrarily.
        
        :param query_arena: query arena
        :type query_arena: FingerprintArena
        :param k: number of nearest neighbors to find (default: 3)
        :type k: positive integer
        :param threshold: minimum similarity threshold (default: 0.7)
        :type threshold: float between 0.0 and 1.0, inclusive
        :returns: SearchResult
        """
        for query_arena in queries.iter_arenas(arena_size):
            result = search.knearest_tanimoto_search(query_arena, self, threshold)
            for (query_id, hits) in zip(query_arena.arena_ids, result.iter_ids_and_scores()):
                yield query_id, hits


# TODO: push more of this malloc-management down into C
class ChemFPOrderedPopcount(ctypes.Structure):
    _fields_ = [("popcount", ctypes.c_int),
                ("index", ctypes.c_int)]


_methods = bitops.get_methods()
_has_popcnt = "POPCNT" in _methods
_has_ssse3 = "ssse3" in _methods

def get_optimal_alignment(num_bits):
    if num_bits <= 32:
        # Just in case!
        if num_bits <= 8:
            return 1
        return 4

    # Since the ssse3 method must examine at least 512 bits while the
    # Gillies method doesn't, this puts the time tradeoff around 210 bits.
    # I decided to save a bit of space and round that up to 224 bits.
    # (Experience will tell us if 256 is a better boundary.)
    if num_bits <= 224:
        return 8

    # If you have POPCNT (and you're using it) then there's no reason
    # to use a larger alignment
    if _has_popcnt:
        if num_bits >= 768:
            if bitops.get_alignment_method("align8-large") == "POPCNT":
                return 8
        else:
            if bitops.get_alignment_method("align8-small") == "POPCNT":
                return 8

    # If you don't have SSSE3 or you aren't using it, then use 8
    if not _has_ssse3 or bitops.get_alignment_method("align-ssse3") != "ssse3":
        return 8

    # In my timing tests:
    #    Lauradoux takes 12.6s
    #    ssse3 takes in 9.0s
    #    Gillies takes 22s


    # Otherwise, go ahead and pad up to 64 bytes
    # (Even at 768 bits/96 bytes, the SSSE3 method is faster.)
    return 64


def fps_to_arena(fps_reader, metadata=None, reorder=True, alignment=None):
    if metadata is None:
        metadata = fps_reader.metadata
    num_bits = metadata.num_bits
    if not num_bits:
        num_bits = metadata.num_bytes * 8
    #assert num_bits

    if alignment is None:
        alignment = get_optimal_alignment(num_bits)

    storage_size = metadata.num_bytes
    if storage_size % alignment != 0:
        n = alignment - storage_size % alignment
        end_padding = "\0" * n
        storage_size += n
    else:
        end_padding = None

    ids = []
    unsorted_fps = StringIO()
    for (id, fp) in fps_reader:
        unsorted_fps.write(fp)
        if end_padding:
            unsorted_fps.write(end_padding)
        ids.append(id)

    unsorted_arena = unsorted_fps.getvalue()
    unsorted_fps.close()
    unsorted_fps = None


    if not reorder or not metadata.num_bits:
        start_padding, end_padding, unsorted_arena = _chemfp.make_unsorted_aligned_arena(
            unsorted_arena, alignment)
        return FingerprintArena(metadata, alignment, start_padding, end_padding, storage_size,
                                unsorted_arena, "", ids)

    # Reorder
        
    ordering = (ChemFPOrderedPopcount*len(ids))()
    popcounts = array.array("i", (0,)*(metadata.num_bits+2))

    start_padding, end_padding, unsorted_arena = _chemfp.make_sorted_aligned_arena(
        num_bits, storage_size, unsorted_arena, len(ids),
        ordering, popcounts, alignment)

    new_ids = [ids[item.index] for item in ordering]
    return FingerprintArena(metadata, alignment,
                            start_padding, end_padding, storage_size,
                            unsorted_arena, popcounts.tostring(), new_ids)
