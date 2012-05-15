import shared
import os
import shutil
import sys

def verbose(message):
  """Print optional verbosity."""
  if shared.verbosity > 0:
    if type(message) == list:
      print >> sys.stderr, '+', ' '.join(message)
    else:
      print >> sys.stderr, message

def recreate_dir(dir):
  if os.path.exists(dir):
    shutil.rmtree(dir)
  os.makedirs(dir)
  return dir

# vim: ts=8:sw=2:tw=120:et:
