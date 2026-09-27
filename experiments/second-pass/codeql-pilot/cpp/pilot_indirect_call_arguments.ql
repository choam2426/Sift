import cpp

// Source positions of arguments at unresolved Code2 calls. No target binding.
from ExprCall call, FieldAccess field, Function enclosing, Expr argument, int index
where
  call.getExpr() = field and
  field.getTarget().getName() = "Code2" and
  not exists(call.getTarget()) and
  enclosing = call.getEnclosingFunction() and
  enclosing.getLocation().getFile().getRelativePath() = "C/XzDec.c" and
  argument = call.getArgument(index)
select
  enclosing.getLocation().getFile().getRelativePath(),
  enclosing.getLocation().getStartLine(),
  enclosing.getName(),
  call.getLocation().getStartLine(),
  call.getLocation().getStartColumn(),
  call.getLocation().getEndLine(),
  call.getLocation().getEndColumn(),
  index,
  argument.getLocation().getStartLine(),
  argument.getLocation().getStartColumn(),
  argument.getLocation().getEndLine(),
  argument.getLocation().getEndColumn()
