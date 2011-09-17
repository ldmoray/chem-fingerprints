"""sdf_reader - iterate through records in an SD file"""

# This is used by the command-line SDF reader, used when the source
# fingerprints are already encoded in fields of an SD file.

# It's also used by the RDKit parser - see the comments there.


from __future__ import absolute_import
from . import ParseError
from . import io

__all__ = ["open_sdf", "iter_sdf_records", "iter_two_tags", "iter_title_and_tag"]

import sys
import re
import chemfp

class SDFParseError(ParseError):
    def __init__(self, msg, filename, lineno):
        super(SDFParseError, self).__init__(msg, filename, lineno)
        self.msg = msg
        self.filename = filename
        self.lineno = lineno
    def __repr__(self):
        return "SDFParseError(%r, %r, %r)" % (self.msg, self.filename, self.lineno)
    def __str__(self):
        return self.msg

def ignore_parse_errors(msg, location):
    pass

def report_parse_errors(msg, location):
    sys.stderr.write("ERROR: %s %s. Skipping.\n" % (msg, location.where()))

def strict_parse_errors(msg, location):
    raise SDFParseError(msg + " " + location.where(),
                        location.lineno, location.name)

_parse_error_handlers = {
    "ignore": ignore_parse_errors,
    "report": report_parse_errors,
    "strict": strict_parse_errors,
    }

def get_parse_error_handler(name_or_callable="strict"):
    try:
        return _parse_error_handlers[name_or_callable]
    except KeyError:
        raise ValueError("'errors' must be one of %s" % ", ".join(sorted(_parse_error_handlers)))



# Do a quick check that the SD record is in the correct format
_sdf_check_pat = re.compile(r"""
.*\n     # line 1
.*\n     # line 2
.*\n     # line 3
         # next are the number of atoms and bonds. This pattern allows
         #  '  0', ' 00', '000', '00 ', '0  ' and ' 0 ', which is the
         # same as checking for field.strip().isdigit()
         # The escape '\040' is for the space character
(\040\040\d|\040\d\d|\d\d\d|\d\d\040|\d\040|\040\d\040)  # number of bonds
(\040\040\d|\040\d\d|\d\d\d|\d\d\040|\d\040|\040\d\040)  # number of bonds
        # Only space and digits are allowed before the required V2000 or V3000
[\0400-9]{28}V(2000|3000)
""", re.X)

class FileLocation(object):
    """A mutable instance used to track record title and position information

    You may pass one of these to the readers to that information. I'm
    a bit unsure about doing it this way but I liked the options of
    passing back a 2-ple of (record, position) or records with an
    attribute like record.position even less.

    WARNING: the attributes '.lineno', and '._record' be set-able.
    Passing in a non-FileLocation object may cause interoperability
    problems in the future.
    """
    def __init__(self, name=None):
        self.name = name
        self.lineno = 1
        self._record = None  # internal variable; it only valid enough to get the title
    @property
    def title(self):
        # The title isn't needed for most cases so don't extract it unless needed
        if self._record is None:
            return None
        return self._record[:self._record.find("\n")].strip()
    
    def where(self):
        s = "at line %s" % (self.lineno,)
        if self.name is not None:
            s += " of %r" % (self.name,)
        title = self.title
        if title:
            s += " (title=%r)" % (title,)
        return s

    def info(self):
        return dict(name=self.name, lineno=self.lineno, title=self.title)

def open_sdf(source=None, decompressor="auto", errors="strict", location=None):
    """Open an SD file and return an iterator over the SD records, as blocks of text

    source - input source. Can be None (for sys.stdin), the input filename
        as a string, or a file object.
    errors - one of "strict" (default), "log", or "ignore". Other values are experimental
    location - experimental location tracking.
    """
    # XXX Adapater until I remove the old decompressor code
    if decompressor == "auto":
        format = None
    elif decompressor == "gzip":
        format = "sdf.gz"
    elif decompressor == "bz2":
        format = "sdf.bz2"
    elif decompressor == "none":
        format = "sdf"
    else:
        raise AssertionError(decompressor)
    format_name, compression = io.normalize_format(source, format)
    fileobj = io.open_compressed_input_universal(source, compression)
    return iter_sdf_records(fileobj, errors, location)

# My original implementation used a slow line-oriented parser.  That
# was decently fast, but this version, which reads a block at a time
# and works directly on those blocks, is over 3 times as fast. It's
# also a lot more complicated

def iter_sdf_records(fileobj, errors="strict", location=None):
    """Iterate over records in an SD file, returning records as blocks of text

    fileobj - input stream. If fileobj.name exists then use it in error messages
    errors - one of "strict" (default), "log", or "ignore". Other values are experimental
    location - experimental location tracking
    """
    if location is None:
        location = FileLocation()
    if location.name is None:
        location.name = getattr(fileobj, "name", None)
    if isinstance(errors, basestring):
        error = get_parse_error_handler(errors)
    else:
        error = errors
    pushback_buffer = ''
    records = None
    while 1:
        if not records:
            read_data = fileobj.read(32768)
            if not read_data:
                # No more data from the file. If there is something in the
                # pushback buffer then it's an incomplete record
                if pushback_buffer:
                    if pushback_buffer.endswith("\n$$$$"):
                        # The file is missing the terminal newline. Compensate.
                        # This will cause an extra read after the known end-of-file.
                        # (Is that a problem? It's not supposed to be one.)
                        pushback_buffer += "\n"
                    else:
                        location._record = None
                        if location.lineno == 1:
                            # No records read. Wrong format.
                            error("Could not find a valid SD record", location)
                        else:
                            error(
   "unexpected content at the end of the file (perhaps the last record is truncated?)",
                                location)
                        break
                else:
                    # We're done!
                    break
            # Join the two blocks of text. This should be enough to
            # have lots of records, so split, and the last term is
            # either a partial record or the empty string. Keep track
            # of that for use in the next go-around.
            records = (pushback_buffer + read_data).split("\n$$$$\n")
            pushback_buffer = records.pop()  # either '' or a partial record

            # It is possible though unlikely that the merged blocks of
            # text contains only an incomplete record, so this might
            # loop again. However, the joining and searching is an
            # O(n**2) operation, so I don't want to do that too often.
            # While it's possible to fix this, there should be no
            # reason to support huge records - they don't exist unless
            # you are really stretching and doing things like storing
            # images or other large data in the SD tags.
            # To prevent timing problems, don't allow huge records.
            if len(pushback_buffer) > 2000000:
                location._record = None
                error("record is too large for this reader", location)
                return
        else:
            # We have a set of records, one string per record. Pass them back.
            for record in records:
                # A simple, quick check that it looks about right
                if not _sdf_check_pat.match(record):
                    location._record = record
                    error("incorrectly formatted record", location)
                    # If the error callback returns then just skip the record
                else:
                    record += "\n$$$$\n"  # restore the split text
                    location._record = record
                    yield record
                location.lineno += record.count("\n")
            records = None


# This is complicated. I tried implementing this search with a regular
# expression but it was about 30% slower than this more direct search.

# Note: tag_substr must contain the "<" and ">"
def _find_tag_data(rec, tag_substr):
    "Return the first data line for the given tag substring, or return None"
    startpos = 0
    while 1:
        tag_start = rec.find(tag_substr, startpos)
        if tag_start == -1:
            return None

        # rfind cannot return -1 because _sdf_check_pat verified there
        # are at least 3 newlines. The +1 is safe because there's at
        # least the "<" and ">" from the tag.
        tag_line_start = rec.rfind("\n", 0, tag_start) + 1
        if rec[tag_line_start] != ">":
            # This tag is not on a data tag line. It might be the value for
            # some of the text field.
            startpos = tag_start + 1
            continue

        # This is an actual tag line. Find the start of the next line.
        # The record must end with "\n$$$$\n" so find will never return -1
        # and never return the last character position.
        next_line_start = rec.find("\n", tag_start) + 1

        # These might occur if there is no data content
        if rec[next_line_start]==">" or rec[next_line_start:next_line_start+4]=="$$$$":
            return ""

        # Otherwise, get up to the end of the line
        return rec[next_line_start:rec.find("\n", next_line_start)]

# These are not legal tag characters (while others may be against the
# SD file spec, these will break the parser)
_bad_char = re.compile(r"[<>\n\r\t\0]")

def iter_two_tags(sdf_iter, tag1, tag2):
    """Iterate over SD records to get the data lines for tag1 and tag2

    sdf_iter - an iterator which returns SD records
    tag1 - the name of the first tag
    tag2 - the name of the second tag

    Each record yields a (tag1_value, tag2_value) 2-ple. If a tag is
    present then the value is from its first data line (or the empty
    string if there is no line). If there are multiple fields with
    the same name then use the first one. If a tag does not exist,
    return None.
    """
    m = _bad_char.search(tag1)
    if m:
        raise TypeError("tag1 must not contain the character %r" % (m.group(0),))
    m = _bad_char.search(tag2)
    if m:
        raise TypeError("tag2 must not contain the character %r" % (m.group(0),))
        
    tag1_substr = "<" + tag1 + ">"
    tag2_substr = "<" + tag2 + ">"
    for rec in sdf_iter:
        yield _find_tag_data(rec, tag1_substr), _find_tag_data(rec, tag2_substr)

def iter_title_and_tag(sdf_iter, tag):
    """Iterate over SD records to get the title line and data line for the specified tag

    sdf_iter - an iterator over SD records, as text
    tag - the name of the tag value to return

    Each record yields a (title, tag_value) 2-ple where the title is
    the first line of the SD record (not a tag!) and the tag_value
    comes from the first data line for the given tag. If the tag is
    present multiple times, use the first match. If the data line is
    missing, the value is"". If the tag does not exist, the value is None.
    """
    m = _bad_char.search(tag)
    if m:
        raise TypeError("tag must not contain the character %r" % (m.group(0),))
    
    tag_substr = "<" + tag + ">"
    for rec in sdf_iter:
        yield rec[:rec.find("\n")].strip(), _find_tag_data(rec, tag_substr)

def iter_tag_and_record(sdf_iter, tag):
    m = _bad_char.search(tag)
    if m:
        raise TypeError("tag must not contain the character %r" % (m.group(0),))

    tag_substr = "<" + tag + ">"
    for rec in sdf_iter:
        yield _find_tag_data(rec, tag_substr), rec
