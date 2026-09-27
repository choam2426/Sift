import cpp

// AST containment: an assignment or call lies in an if branch. This is a
// syntactic relation; it does not prove that the branch is reachable.
from IfStmt branch, Expr effect, Function enclosing, string branchSide
where
  enclosing = branch.getEnclosingFunction() and
  enclosing = effect.getEnclosingFunction() and
  enclosing.getLocation().getFile().getRelativePath() = "C/XzDec.c" and
  (effect instanceof Assignment or effect instanceof FunctionCall) and
  effect.getLocation().getFile().getRelativePath() = "C/XzDec.c" and
  (
    branchSide = "then" and effect.getEnclosingStmt().getParent*() = branch.getThen()
    or
    branchSide = "else" and effect.getEnclosingStmt().getParent*() = branch.getElse()
  )
select
  enclosing.getLocation().getFile().getRelativePath(),
  enclosing.getLocation().getStartLine(),
  enclosing.getName(),
  branch.getCondition().getLocation().getStartLine(),
  branch.getCondition().getLocation().getStartColumn(),
  branch.getCondition().getLocation().getEndLine(),
  branch.getCondition().getLocation().getEndColumn(),
  effect.getLocation().getStartLine(),
  effect.getLocation().getStartColumn(),
  effect.getLocation().getEndLine(),
  effect.getLocation().getEndColumn(),
  branchSide
