#!/usr/bin/env python

from distutils.core import setup, Extension

setup(name = "chemfp",
      version = "1.0b1",
      description = "Cheminformatics fingerprint tools",
      author = "Andrew Dalke",
      author_email = 'dalke@dalkescientific.com',
      url = "http://code.google.com/p/chem-fingerprints/",
      packages = ["chemfp", "chemfp.commandline"],
      scripts = ["ob2fps", "oe2fps", "rdkit2fps", "sdf2fps", "simsearch", "fpsmerge"],

      ext_modules = [Extension("_chemfp",
                               ["src/bitops.c", "src/chemfp.c",
                                "src/heapq.c", "src/fps.c",
                                "src/searches.c",
                                "src/python_api.c"])],
     )

