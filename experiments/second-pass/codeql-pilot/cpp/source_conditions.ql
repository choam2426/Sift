import cpp

// Extract explicit branch conditions without interpreting them as defenses.
from IfStmt branch, Function enclosing, Expr condition
where
  enclosing = branch.getEnclosingFunction() and
  condition = branch.getCondition() and
  branch.getFile().getRelativePath() = "C/XzDec.c"
select
  enclosing.getLocation().getStartLine(),
  enclosing.getName(),
  branch.getLocation().getStartLine(),
  condition.getLocation().getStartLine(),
  condition.getLocation().getStartColumn(),
  condition.getLocation().getEndLine(),
  condition.getLocation().getEndColumn(),
  condition.toString()
