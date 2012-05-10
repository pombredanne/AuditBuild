
import json
import os
import sys
import tempfile
import time
import warnings

class BuildAudit:
  """Class to manage and persist the audit of a build into prereqs and targets.

  The files used during a build can be categorized as prerequisites (read from)
  and targets (written to). Some are both, but a write beats a read so any
  modified file is treated as a target. This class manages a data structure
  categorizing these file sets. It also records the time delta for each file from
  start of build to last use.

  """
  def __init__(self, dbdir='.', dbname='BuildAudit.json'):
    self.dbfile = os.path.join(dbdir, dbname)
    try:
      self.db = json.load(open(self.dbfile))
    except IOError:
      self.db = {}
    self.audit = {'PREREQS':{}, 'INTERMS':{}, 'TARGETS':{}, 'NOTUSED':{}, 'CMDLINE':sys.argv}
    self.new_prereqs = self.audit['PREREQS']
    self.new_interms = self.audit['INTERMS']
    self.new_targets = self.audit['TARGETS']
    self.new_notused = self.audit['NOTUSED']

  def has(self, key):
    return key in self.db

  def all_keys(self):
    return sorted(self.db.keys())

  def old_prereqs(self, key):
    return self.db[key]['PREREQS'] if key in self.db else {}

  def old_interms(self, key):
    return self.db[key]['INTERMS'] if key in self.db else {}

  def old_targets(self, key):
    return self.db[key]['TARGETS'] if key in self.db else {}

  def old_notused(self, key):
    return self.db[key]['NOTUSED'] if key in self.db else {}

  def get_reftime(self, indir):
    """Return a unique file reference time.

    Different filesystems have different granularities for time
    stamps. For instance, ext3 records one-second granularity while
    ext4 records nanoseconds. Regardless of host filesystem, this
    method guarantees to return a timestamp value newer than any
    file previously accessed within the same filesystem and same
    thread, and no newer than any timestamp created subsequently.

    """
    def get_time_past(previous):
      this_time = 0
      while True:
        with tempfile.TemporaryFile(dir=indir) as fp:
          this_time = os.fstat(fp.fileno()).st_mtime
        if this_time > previous:
          break
        time.sleep(0.1)
      return this_time

    old_time = get_time_past(0)
    self.reftime = get_time_past(old_time)

  def update(self, key, basedir, replace):
    # Note: do NOT use os.walk to traverse the tree.
    # It has a way of updating symlink atimes.
    def visit(data, parent, files):
      # Assume hidden dirs contain stuff we don't care about
      if not parent.startswith('.'):
        for f in files:
          path = os.path.join(parent, f)
          if not os.path.isdir(path):
            rpath = os.path.relpath(path, basedir)
            stats = os.lstat(path)
            adelta = stats.st_atime - self.reftime
            mdelta = stats.st_mtime - self.reftime
            value = str(adelta) + ' ' + str(mdelta)
            if mdelta >= 0:
              if adelta > mdelta:
                self.new_interms[rpath] = 'I ' + value
              else:
                self.new_targets[rpath] = 'T ' + value
            elif adelta >= 0:
              self.new_prereqs[rpath] = 'P ' + value
            else:
              self.new_notused[rpath] = 'N'
    os.path.walk(basedir, visit, None)

    if not self.new_prereqs:
      warnings.warn("Empty prereq set - check for 'noatime' mount")
    else:
      if replace or not self.has(key):
        self.db[key] = {'PREREQS':{}, 'INTERMS':{}, 'TARGETS':{}, 'NOTUSED':{}, 'CMDLINE':sys.argv}
      old_prqs = self.old_prereqs(key)
      old_ints = self.old_interms(key)
      old_tgts = self.old_targets(key)
      if set(self.new_prereqs) - set(old_prqs) or \
         set(self.new_interms) - set(old_ints) or \
         set(self.new_targets) - set(old_tgts):
        self.new_prereqs.update(old_prqs)
        self.new_interms.update(old_ints)
        self.new_targets.update(old_tgts)
        timestr = "%s (%s)" % (str(self.reftime), time.ctime(self.reftime))
        self.db[key] = {'PREREQS':self.new_prereqs, 'INTERMS':self.new_interms, 'TARGETS':self.new_targets,
            'NOTUSED':self.new_notused, 'CMDLINE':sys.argv, 'REFTIME':timestr}
        print >> sys.stderr, "updating database for '%s'" % (key)
        with open(self.dbfile, "w") as fp:
          json.dump(self.db, fp, indent=2)
          fp.write('\n');  # json does not add trailing newline
