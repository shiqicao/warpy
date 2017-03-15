#!/usr/bin/env python

from __future__ import print_function
import os, sys, re, subprocess, tempfile
from subprocess import Popen, PIPE

CLEANUP = False

WAST2WASM = os.environ.get("WAST2WASM", "wast2wasm")
WARPY = os.environ.get("WARPY", "./warpy.py")

def read_forms(string):
    forms = []
    form = ""
    depth = 0
    line = 0
    pos = 0
    while pos < len(string):
        # Keep track of line number
        if string[pos] == '\n': line += 1
        
        # Handle top-level elements
        if depth == 0:
            # Add top-level comments
            if string[pos:pos+2] == ";;":
                end = string.find("\n", pos)
                if end == -1: end == len(string)
                forms.append(string[pos:end])
                pos = end
                continue

            # Ignore whitespace between top-level forms
            if string[pos] in (' ', '\n', '\t'):
                pos += 1
                continue

        # Read a top-level form
        if string[pos] == '(': depth += 1
        if string[pos] == ')': depth -= 1
        if depth == 0 and not form:
            raise Exception("garbage on line %d: '%s'" % (
                line, string[pos:pos+80]))
        form += string[pos]
        if depth == 0 and form:
            forms.append(form)
            form = ""
        pos += 1
    return forms

def parse_val(val):
    if   val == '':
        return (None, '')
    type = val[0:3]
    if type in ["i32", "i64"]:
        if val[10:12] == "0x":
            return (int(val[10:], 16),
                    "%s:%s" % (val[10:], type))
        else:
            return (int(val[10:]),
                    "%s:%s" % (hex(int(val[10:])), type))
    elif type in ["f32", "f64"]:
        if val[10:14] == "nan:":
            # TODO: how to handle this correctly
            return (float('nan'),
                    "nan:%s" % type)
        elif val[10:12] == "0x":
            return (float.fromhex(val[10:]),
                    "%.6f:%s" % (float.fromhex(val[10:]), type))
        else:
            return (float(val[10:]),
                    "%.6f:%s" % (float(val[10:]), type))
    else:
        raise Exception("invalid value '%s'" % val)

def test_assert(mode, wasm, func, args, expected, returncode=0):
    # convert back to strings for the call
    test_args = [str(a) for a in args]

    print("Testing(%s) %s(%s) = %s" % (
        mode, func, ", ".join(test_args), expected))

    # Convert args back to string
    cmd = [WARPY, wasm, func] + test_args 
    #print("Running: %s" % " ".join(cmd))

    sp = Popen(cmd, stdout=PIPE, stderr=PIPE)
    (out, err) = sp.communicate()
    if sp.returncode != returncode:
        raise Exception("Failed (retcode expected: %d, got: %d)\n%s" % (
            returncode, sp.returncode, err))

    out = out.rstrip("\n")
    #print("  out: '%s'" % out)
    #print("  err: %s" % err)
    if expected != out:
        raise Exception("Failed:\n  expected: '%s'\n  got: '%s'" % (
            expected, out))

def test_assert_return(wasm, form):
    # params, return
    m = re.search('^\(assert_return\s+\(invoke\s+"([^"]+)"\s+(\(.*\))\s*\)\s*(\([^)]+\))\s*\)\s*$', form)
    if not m:
        # no params, return
        m = re.search('^\(assert_return\s+\(invoke\s+"([^"]+)"\s*\)\s+()(\([^)]+\))\s*\)\s*$', form)
    if not m:
        # params, no return
        m = re.search('^\(assert_return\s+\(invoke\s+"([^"]+)"\s+(\(.*\))()\s*\)\s*\)\s*$', form)
    if not m:
        # no params, no return
        m = re.search('^\(assert_return\s+\(invoke\s+"([^"]+)"\s*()()\)\s*\)\s*$', form)
    if not m:
        raise Exception("unparsed assert_return: '%s'" % form)
    func = m.group(1)
    if m.group(2) == '':
        args = []
    else:
        args = [parse_val(v)[0] for v in re.split("\)\s*\(", m.group(2)[1:-1])]
    result, expected = parse_val(m.group(3)[1:-1])

    test_assert("return", wasm, func, args, expected)

def test_assert_trap(wasm, form):
    # params
    m = re.search('^\(assert_trap\s+\(invoke\s+"([^"]+)"\s+(\(.*\))\s*\)\s*"([^"]+)"\s*\)\s*$', form)
    if not m:
        # no params
        m = re.search('^\(assert_trap\s+\(invoke\s+"([^"]+)"\s*()\)\s*"([^"]+)"\s*\)\s*$', form)
    if not m:
        raise Exception("unparsed assert_trap: '%s'" % form)
    func = m.group(1)
    if m.group(2) == '':
        args = []
    else:
        args = [parse_val(v)[0] for v in re.split("\)\s*\(", m.group(2)[1:-1])]
    expected = m.group(3)

    test_assert("trap", wasm, func, args, expected, returncode=1)

def run_test_file(test_file):
    print("WAST2WASM: '%s'" % WAST2WASM)
    (t1fd, wast_tempfile) = tempfile.mkstemp(suffix=".wast")
    (t2fd, wasm_tempfile) = tempfile.mkstemp(suffix=".wasm")
    print("wast_tempfile: '%s'" % wast_tempfile)
    print("wasm_tempfile: '%s'" % wasm_tempfile)

    try:
        forms = read_forms(file(test_file).read())

        for form in forms:
            if  ";;" == form[0:2]:
                print(form)
            elif re.match("^\(module\\b.*", form):
                print("Writing WAST module to '%s'" % wast_tempfile)
                file(wast_tempfile, 'w').write(form)
                print("Compiling WASM to '%s'" % wasm_tempfile)
                subprocess.check_call([
                    WAST2WASM,
                    "--no-check-assert-invalid-and-malformed",
                    wast_tempfile,
                    "-o",
                    wasm_tempfile])
            elif re.match("^\(assert_return\\b.*", form):
                #print("%s" % form)
                test_assert_return(wasm_tempfile, form)
            elif re.match("^\(assert_trap\\b.*", form):
                #print("%s" % form)
                test_assert_trap(wasm_tempfile, form)
            elif re.match("^\(assert_invalid\\b.*", form):
                #print("ignoring assert_invalid")
                pass
            else:
                raise Exception("unrecognized form '%s...'" % form[0:20])
    finally:
        if CLEANUP:
            print("Removing tempfiles")
            os.remove(wast_tempfile)
            os.remove(wasm_tempfile)
        else:
            print("Leaving tempfiles: %s" % (
                [wast_tempfile, wasm_tempfile]))

if __name__ == "__main__": 
    run_test_file(sys.argv[1])