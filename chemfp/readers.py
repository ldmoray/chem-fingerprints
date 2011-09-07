from __future__ import division

from cStringIO import StringIO
from __builtin__ import open as _builtin_open
import binascii
import _chemfp
import re
import sys
import heapq
import itertools

import chemfp
from chemfp import fps_search
import ctypes

from . import search, io

BLOCKSIZE = 20000

class FPSParseError(Exception):
    def __init__(self, errcode, lineno, filename):
        self.errcode = errcode
        self.lineno = lineno
        self.filename = filename
    def __repr__(self):
        return "FPSParseError(%d, %d, %s)" % (self.errcode, self.lineno, self.filename)
    def __str__(self):
        msg = _chemfp.strerror(self.errcode)
        msg += " at line %d" % (self.lineno,)
        if self.filename is not None:
            msg += " of file %r" % (self.filename,)
        return msg


def open_fps(source, format=None):
    format_name, compression = io.normalize_format(source, format)
    if format_name != "fps":
        raise TypeError("Unknown format %r" % (format_name,))

    infile = io.open_compressed_input_universal(source, compression)
    filename = io.get_filename(source)

    header, lineno, block = read_header(infile, filename)
    return FPSReader(infile, header, lineno, block)


# This never buffers
def _read_blocks(infile):
    while 1:
        block = infile.read(BLOCKSIZE)
        if not block:
            break
        if block[-1:] == "\n":
            yield block
            continue
        line = infile.readline()
        if not line:
            # Note: this might not end with a newline!
            yield block
            break
        yield block + line

            

class FPSReader(object):
    def __init__(self, infile, header, first_fp_lineno, first_fp_block):
        self._infile = infile
        self._filename = getattr(infile, "name", "<unknown>")
        self.header = header
        self._first_fp_lineno = first_fp_lineno
        self._first_fp_block = first_fp_block
        self._expected_hex_len = 2*header.num_bytes_per_fp
        self._hex_len_source = "size in header"

        self._at_start = True
        self._it = None
        self._block_reader = None
        
    def reset(self):
        if self._at_start:
            return
        raise TypeError("FPSReader instances do not support reset()")
        
    def iter_blocks(self):
        if self._block_reader is None:
            self._block_reader = iter(self._iter_blocks())
        return self._block_reader

    def _iter_blocks(self):
        if not self._at_start:
            raise TypeError("Already iterating")
        
        self._at_start = False

        if self._first_fp_block is None:
            return
        
        block_stream = _read_blocks(self._infile)
        yield self._first_fp_block
        for block in block_stream:
            yield block

    def iter_arenas(self, arena_size = 1000):
        id_fps = iter(self)
        while 1:
            arena = chemfp.load_fingerprints(itertools.islice(id_fps, 0, arena_size),
                                             header = self.header,
                                             sort = False)
            if not arena:
                break
            yield arena
        
    def iter_rows(self):
        unhexlify = binascii.unhexlify
        lineno = self._first_fp_lineno
        expected_hex_len = self._expected_hex_len
        for block in self.iter_blocks():
            for line in block.splitlines(True):
                err = _chemfp.fps_line_validate(expected_hex_len, line)
                if err:
                    XXXX
                    raise Exception(errcode, expected_hex_len, line)
                yield line.split("\t")
                lineno += 1

    def __iter__(self):
        unhexlify = binascii.unhexlify
        lineno = self._first_fp_lineno
        expected_hex_len = self._expected_hex_len
        for block in self.iter_blocks():
            for line in block.splitlines(True):
                err, id_fp = _chemfp.fps_parse_id_fp(expected_hex_len, line)
                if err:
                    # Include the line?
                    raise FPSParseError(err, lineno, self._filename)
                yield id_fp
                lineno += 1

    def count_tanimoto_hits_fp(self, query_fp, threshold=0.7):
        return fps_search.count_tanimoto_hits_fp(query_fp, self, threshold)

    def count_tanimoto_hits_arena(self, query_arena, threshold=0.7):
        return fps_search.count_tanimoto_hits_arena(query_arena, self, threshold)

    def threshold_tanimoto_search_fp(self, query_fp, threshold=0.7):
        return fps_search.threshold_tanimoto_search_fp(query_fp, self, threshold)

    def threshold_tanimoto_search_arena(self, query_arena, threshold=0.7):
        return fps_search.threshold_tanimoto_search_all(query_arena, self, threshold)

    def knearest_tanimoto_search_fp(self, query_fp, k=3, threshold=0.7):
        return fps_search.knearest_tanimoto_search_fp(query_fp, self, k, threshold)

    def knearest_tanimoto_search_arena(self, query_arena, k=3, threshold=0.7):
        return fps_search.knearest_tanimoto_search_all(query_arena, self, k, threshold)


# XXX Use Python's warning system
def warn_to_stderr(filename, lineno, message):
    where = _where(filename, lineno)
    sys.stderr.write("WARNING: %s at %s\n" % (message, where))

_whitespace = re.compile(r"[ \t\n]")
def read_header(f, filename, warn=warn_to_stderr):
    header = io.Header()

    lineno = 1
    for block in _read_blocks(f):
        # A block must be non-empty
        start = 0
        while 1:
            c = block[start:start+1]
            if c == "":
                # End of the block; get the next one
                break
            if c != '#':
                # End of the header. This block contains the first fingerprint line
                block = block[start:]
                if header.num_bits is None:
                    # We can figure this out from the fingerprint on the first line
                    m = _whitespace.search(block)
                    if m is None:
                        raise TypeError(block)
                    i = m.end()-1 # Back up from the whitespace
                    if i % 2 == 1:
                        raise TypeError(block)
                    header.num_bits = i * 4
                    
                return header, lineno, block

            start += 1 # Skip the '#'
            end = block.find("\n", start)
            if end == -1:
                # Only happens when the last line of the file contains
                # no newlines. In that case, we're at the last block.
                line = block[start:]
                start = len(block)
            else:
                line = block[start:end]
                start = end+1

            # Right! We've got a line. Check if it's magic
            # This is the only line which cannot contain a '='
            if lineno == 1:
                if line.rstrip() == "FPS1":
                    lineno += 1
                    continue
                assert "=" not in line, line
                
            assert "=" in line, line
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()

            if key == "num_bits":
                try:
                    header.num_bits = int(value)
                    if not (header.num_bits > 0):
                        raise ValueError
                except ValueError:
                    raise TypeError(
                        "num_bits header must be a positive integer, not %r: %s" %
                        (value, _where(filename, lineno)))
            elif key == "software":
                header.software = value
            elif key == "type":
                # Should I have an auto-normalization step here which
                # removes excess whitespace?
                #header.type = normalize_type(value)
                header.type = value
            elif key == "source":
                header.source = value
            elif key == "date":
                header.date = value
            else:
                print "UNKNOWN", repr(line), repr(key), repr(value)
                #warn(filename, lineno, "Unknown header %r" % (value,))
            lineno += 1

    # Reached the end of file. No fingerprint lines and nothing left to process.
    return header, lineno, None

