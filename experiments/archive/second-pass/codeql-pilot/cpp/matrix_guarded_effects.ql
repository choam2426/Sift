import cpp
import semmle.code.cpp.controlflow.Guards

// A guard controlling a local assignment or call. This does not prove that
// either branch is reachable or that the effect is security relevant.
from IfStmt branch, GuardCondition guard, Expr effect, Function enclosing,
  boolean testIsTrue
where
  guard = branch.getCondition() and
  enclosing = branch.getEnclosingFunction() and
  enclosing = effect.getEnclosingFunction() and
  enclosing.getLocation().getFile().getRelativePath().regexpMatch("C/.*") and
  (effect instanceof Assignment or effect instanceof FunctionCall) and
  guard.controls(effect.getBasicBlock(), testIsTrue) and
  effect.getLocation().getFile().getRelativePath().regexpMatch("C/.*")
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
  testIsTrue
