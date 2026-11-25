"""Check that reformatting or commenting did not change what the code does.
usage: check_same.py <original folder> <current folder>
Python: the parsed program must be identical once docstrings are ignored (comments and
layout never count).
Firmware: handled separately by comparing the built .hex files (see the journal).

For every *.py file directly inside <original folder> (sub-folders are not visited), the
file of the same name in <current folder> is parsed and compared with it. Files that
exist only in <current folder> are not looked at.

Prints one line per problem:
  MISSING <path>            the file is absent from <current folder>
  SYNTAX ERROR <path> ...   one of the two versions does not parse (the path shown is
                            always the current one)
  DIFFERENT <file name>     the two versions parse to different programs
then a summary line "<n> Python files compared, <m> problem(s)".
Exit status is 0 when there is no problem, 1 otherwise. Needs only the standard library.
"""

import ast, sys, os, glob


def shape(path):
    """Return a text form of the parsed program in the file at path, without docstrings.

    Two files give the same text exactly when they parse to the same syntax tree after
    their docstrings are removed. Comments, blank lines, line breaks and spacing are not
    part of the syntax tree, so they never make a difference; line numbers are left out
    of the text as well.
    """
    tree = ast.parse(open(path).read())
    for node in ast.walk(tree):  # drop docstrings: they are documentation, not behaviour
        body = getattr(node, "body", None)
        # A docstring is a bare string as the first statement of a body...
        if (
            isinstance(body, list)
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(getattr(body[0], "value", None), ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            # ...and only modules, functions and classes have one. A bare string at the
            # top of, say, a loop body is kept.
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                # A body that held nothing but its docstring becomes a lone "pass", because
                # a body may not be empty.
                node.body = body[1:] or [ast.Pass()]
    return ast.dump(tree)


orig, cur = sys.argv[1], sys.argv[2]  # the two folders to compare
bad = 0  # number of problems found
for f in sorted(glob.glob(os.path.join(orig, "*.py"))):
    g = os.path.join(cur, os.path.basename(f))  # the same file name in the current folder
    if not os.path.exists(g):
        print("MISSING", g)
        bad += 1
        continue
    try:
        same = shape(f) == shape(g)
    except SyntaxError as e:
        print("SYNTAX ERROR", g, e)
        bad += 1
        continue
    if not same:
        print("DIFFERENT", os.path.basename(f))
        bad += 1
# The count printed is the number of files in the original folder, missing ones included.
print("%d Python files compared, %d problem(s)" % (len(glob.glob(os.path.join(orig, "*.py"))), bad))
sys.exit(1 if bad else 0)
