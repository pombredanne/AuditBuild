import shared
import os
import shutil
import subprocess
import sys
import xml.dom.minidom

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

def dirnames(files):
  dirs = {}
  for fn in files:
    dir = os.path.dirname(fn)
    if len(dir) > 0:
      dirs[dir] = True
  return dirs

def getText(nodelist):
  txt = []
  for node in nodelist:
    if node.nodeType == node.TEXT_NODE:
      txt.append(node.data)
  return ''.join(txt)

def svn_get_url(dir):
  cmd = ['svn', 'info', '--xml']
  subproc = subprocess.Popen(cmd, cwd=dir, stdout=subprocess.PIPE, stderr=open(os.devnull))
  output = subproc.communicate()
  if subproc.returncode != 0:
    sys.exit(2)
  dom = xml.dom.minidom.parseString(output[0])
  url = dom.getElementsByTagName('url')
  urltxt = getText(url[0].childNodes)
  return urltxt

def svn_export_dirs(baseurl, basedir, prereqs):
  rc = 0
  recreate_dir(basedir)
  for dir in sorted(dirnames(prereqs)):
    url = os.path.join(baseurl, dir)
    to = os.path.join(basedir, dir)
    parent = os.path.dirname(to)
    if not os.path.exists(parent):
      os.makedirs(parent)
    cmd = ['svn', 'export', '--quiet', '--depth', 'files', url, to]
    verbose(cmd)
    if subprocess.call(cmd) != 0:
      rc = 2
  return rc

def svn_export_files(baseurl, basedir, prereqs):
  rc = 0
  recreate_dir(basedir)
  for dir in sorted(dirnames(prereqs)):
    bd = os.path.join(basedir, dir)
    if not os.path.exists(bd):
      os.makedirs(bd)
  for fn in sorted(prereqs):
    cmd = ['svn', 'export', '--quiet', os.path.join(baseurl, fn), os.path.join(basedir, fn)]
    verbose(cmd)
    if subprocess.call(cmd) != 0:
      rc = 2
  return rc

def svn_full_extract(bom, todir):
  if os.path.exists(todir):
    shutil.rmtree(todir)
  cmd = ['sparse', 'co', '--quiet', bom, todir]
  verbose(cmd)
  return subprocess.call(cmd)

def run_with_stdin(cmd, input):
  verbose(cmd)
  subproc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
  for line in input:
    if shared.verbosity > 1:
      print '<', line
    print >> subproc.stdin, line
  subproc.stdin.close()
  if subproc.wait():
    sys.exit(2)

# vim: ts=8:sw=2:tw=120:et:
