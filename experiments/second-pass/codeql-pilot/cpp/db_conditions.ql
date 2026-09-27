import cpp

// Explicit if conditions and their source spans; not proof of guarding an effect.
from IfStmt branch, Function enclosing, Expr condition
where
  enclosing = branch.getEnclosingFunction() and
  condition = branch.getCondition() and
  enclosing.getLocation().getFile().getRelativePath().regexpMatch("C/.*")
select
  enclosing.getLocation().getFile().getRelativePath(),
  enclosing.getLocation().getStartLine(),
  enclosing.getName(),
  condition.getLocation().getFile().getRelativePath(),
  condition.getLocation().getStartLine(),
  condition.getLocation().getStartColumn(),
  condition.getLocation().getEndLine(),
  condition.getLocation().getEndColumn()
