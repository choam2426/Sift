import cpp

// Source-backed arguments of statically resolved calls; no vulnerability rules.
from FunctionCall call, Function caller, Function callee, int index, Expr argument
where
  caller = call.getEnclosingFunction() and
  callee = call.getTarget() and
  argument = call.getArgument(index) and
  caller.getLocation().getFile().getRelativePath().regexpMatch("C/.*")
select
  caller.getLocation().getFile().getRelativePath(),
  caller.getLocation().getStartLine(),
  caller.getName(),
  callee.getLocation().getFile().getRelativePath(),
  callee.getLocation().getStartLine(),
  callee.getName(),
  call.getLocation().getFile().getRelativePath(),
  call.getLocation().getStartLine(),
  call.getLocation().getStartColumn(),
  call.getLocation().getEndLine(),
  call.getLocation().getEndColumn(),
  index,
  argument.getLocation().getFile().getRelativePath(),
  argument.getLocation().getStartLine(),
  argument.getLocation().getStartColumn(),
  argument.getLocation().getEndLine(),
  argument.getLocation().getEndColumn()
