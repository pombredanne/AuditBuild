import shared
import os
import shutil
import sys

def verbose(cmd):
  """Print verbosity for executed subcommands."""
  if shared.verbosity > 0:
    print >> sys.stderr, '+', ' '.join(cmd)

def recreate_dir(dir):
  if os.path.exists(dir):
    shutil.rmtree(dir)
  os.makedirs(dir)
  return dir

# vim: ts=8:sw=2:tw=120:et:
