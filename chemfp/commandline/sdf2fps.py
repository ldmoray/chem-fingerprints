from __future__ import absolute_import
from __future__ import with_statement

import sys
import re

from .. import argparse, decoders, sdf_reader, io


def _check_num_bits(num_bits,  # from the user
                    fp_num_bits, # not None if the fp decoder know it exactly
                    num_bytes, # length of decoded fp in bytes
                    parser):
    """Check that the number of fingerprint bits and bytes match the user input

    Difficulties: some fingerprints have only a byte length, and the user
    doesn't have to specify the input.

    Returns the number of bits, or calls parser.error if there are problems
    """
    if fp_num_bits is not None:
        # The fingerprint knows exactly how many bits it contains
        if num_bits is None:
            # The user hasn't specified, so go with the exact number
            return fp_num_bits

        # If the user gave a value, make sure it matches
        if num_bits != fp_num_bits:
            parser.error(
                ("the first fingerprint has %(fp_num_bits)s bits which "
                 "is not the same as the --num-bits value of %(num_bits)s") % dict(
                    num_bits=num_bits, fp_num_bits=fp_num_bits))
            raise AssertionError("should not get here")
        return fp_num_bits

    # If the number of bits isn't specified, assume it's exactly
    # enough to fill up the fingerprint bytes.
    if num_bits is None:
        return num_bytes * 8

    # The user specified the number of bits. The first fingerprint
    # has a number of bytes. This must be enough to hold the bits,
    # but only up to 7 bits larger.
    if (num_bits+7)//8 != num_bytes:
        parser.error(
            ("The byte length of the first fingerprint is %(num_bytes)s so --num-bits "
             "must be %(min)s <= num-bits <= %(max)s, not %(num_bits)s") % dict(
                num_bytes=num_bytes, min=num_bytes*8-7, max=num_bytes*8,
                num_bits=num_bits))
        raise AssertError("should not get here")

    # Accept what the user suggested
    return num_bits

parser = argparse.ArgumentParser(
    description="Extract a fingerprint tag from an SD file and generate FPS fingerprints",
    #epilog=epilog,
    #formatter_class=argparse.RawDescriptionHelpFormatter,
    )

parser.add_argument(
    "filename", nargs="?", help="input SD file (default is stdin)", default=None)

parser.add_argument("--title-tag", metavar="TAG", default=None,
            help="get the record title from TAG instead of the first line of the record")
parser.add_argument("--fp-tag", metavar="TAG", 
                    help="get the fingerprint from tag TAG (required)")

parser.add_argument("--num-bits", metavar="INT", type=int,
                    help="use the first INT bits of the input. Use only when the "
                    "last 1-7 bits of the last byte are not part of the fingerprint. "
                    "Unexpected errors will occur if these bits are not all zero.")

parser.add_argument("-o", "--output", metavar="FILENAME",
                    help="save the fingerprints to FILENAME (default=stdout)")
parser.add_argument("--software", metavar="TEXT",
                    help="use TEXT as the software description")
parser.add_argument("--type", metavar="TEXT",
                    help="use TEXT as the fingerprint type description")

# TODO:
# Do I want "--gzip", "--auto", "--none", "--bzip2", and "--decompress METHOD"?
# Do I want to support encoding of the fps output?
# Or, why support all these? Why not just "--in gz", "--in bz2" and be done
#  with it (do I really need to specify the 'auto' and 'none' options?)
parser.add_argument(
    "--decompress", action="store", metavar="METHOD", default="auto",
    help="use METHOD to decompress the input (default='auto', 'none', 'gzip', 'bzip2')")
#parser.add_argument(
#    "--compress", action="store", metavar="METHOD", default="auto",
#    help="use METHOD to compress the output (default='auto', 'none', 'gzip', 'bzip2')")


# This adds --cactvs, --base64 and other decoders to the command-line arguments
decoders._add_decoding_group(parser)

# Support the "--pubchem" option
shortcuts_group = parser.add_argument_group("shortcuts")

class AddSubsKeys(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        namespace.cactvs=True
        # the 1.3 is solely based on the version of the document at
        #  ftp://ftp.ncbi.nlm.nih.gov/pubchem/specifications/pubchem_fingerprints.txt
        namespace.software="CACTVS/unknown"
        namespace.type="CACTVS-E_SCREEN/1.0 extended=2"
        namespace.fp_tag="PUBCHEM_CACTVS_SUBSKEYS"

shortcuts_group.add_argument("--pubchem", nargs=0, action=AddSubsKeys,
   help = ("decode CACTVS substructure keys used in PubChem. Same as "
           "--software=CACTVS/unknown --type 'CACTVS-E_SCREEN/1.0 extended=2' "
           "--fp-tag=PUBCHEM_CACTVS_SUBSKEYS --cactvs"))

###############

_illegal_value_pat = re.compile(r"[\000-\037]")

def main(args=None):
    args = parser.parse_args(args)

    if not args.fp_tag:
        parser.error("argument --fp-tag is required")
    if args.num_bits is not None and args.num_bits <= 0:
        parser.error("--num-bits must be a positive integer")

    fp_decoder_name, fp_decoder = decoders._extract_decoder(parser, args)

    # Open the file for reading records
    location = sdf_reader.FileLocation()
    records = sdf_reader.open_sdf(args.filename, args.decompress, loc=location)

    for attr in ("software", "type"):
        description = getattr(args, attr, None)
        if description is None:
            continue
        m = _illegal_value_pat.search(description)
        if m is None:
            continue
        parser.error("--%(attr)s description may not contain the character %(c)r" % dict(
                attr=attr, c = m.group(0)))

    # Get the title and fingerprints from the records, and set up the
    # error messages for missing title and fingerprints.
    if args.title_tag is not None:
        reader = sdf_reader.iter_two_tags(records, args.title_tag, args.fp_tag)
        MISSING_TITLE = "Missing title tag %s, " % (args.title_tag,)
        MISSING_TITLE += "in the record starting at line %s. Skipping.\n"
        
    else:
        reader = sdf_reader.iter_title_and_tag(records, args.fp_tag)
        MISSING_TITLE = "Empty record title at line %s. Skipping.\n"

    MISSING_FP = ("Missing fingerprint tag %(tag)s in record %(title)r line %(lineno)s. "
                  "Skipping.\n")

    # This is either None or a user-specified integer
    num_bits = args.num_bits

    # I need to get some information from the first record
    first_time = True
    outfile = None       # Don't open it until I'm ready to write the first record
    num_bytes = None     # Will need to get (or at least check) the fingerprint byte length
    expected_fp_num_bits = -1   # 

    def skip(skip_count=[0]):
        if first_time:
            if skip_count[0] > 100:
                raise SystemExit(
                    "ERROR: No fingerprints found in the first 100 records. Exiting.")
            skip_count[0] += 1

    for title, encoded_fp in reader:
        if not title:
            sys.stderr.write(MISSING_TITLE % (location.lineno,))
            skip()
            continue
        if not encoded_fp:
            sys.stderr.write(MISSING_FP % dict(
                tag=args.fp_tag, title=location.title, lineno=location.lineno))
            skip()
            continue
        try:
            fp_num_bits, fp = fp_decoder(encoded_fp)
        except TypeError, err:
            sys.stderr.write(
                ("Could not %(decoder_name)s decode <%(tag)s> value %(encoded_fp)r: %(err)s\n"
                 "  Skipping record %(message)s\n") % dict(
                    decoder_name=fp_decoder_name, tag=args.fp_tag,
                    message=location.where(), err=err, encoded_fp=encoded_fp))
            skip()
            continue
        
        if first_time:
            first_time = False
            num_bytes = len(fp)
            num_bits = _check_num_bits(num_bits, fp_num_bits, num_bytes, parser)
            expected_fp_num_bits = fp_num_bits
            expected_num_bytes = num_bytes

            header = io.Header(num_bits = num_bits,
                               software = args.software,
                               type = args.type,
                               source = args.filename,
                               date = io.utcnow())
            
            # Now I know num_bits and num_bytes
            # Time to create output!
            outfile = io.open_output(args.output)
            with io.ignore_pipe_errors:
                io.write_fps1_magic(outfile)
                io.write_fps1_header(outfile, header)

        else:
            if (fp_num_bits != expected_fp_num_bits or
                len(fp) != expected_num_bytes):
                raise SystemExit(
                    ("ERROR: The %(message)s, tag %(tag)s has an inconsistent "
                     "fingerprint length" % dict(
                         message=location.message(), tag=args.fp_tag)))

        with io.ignore_pipe_errors:
            io.write_fps1_fingerprint(outfile, fp, title)
            
    if first_time:
        # Looks like I didn't find anything.
        sys.stderr.write("WARNING: No input records contained fingerprints. "
                         "No output generated.")

if __name__ == "__main__":
    main()
