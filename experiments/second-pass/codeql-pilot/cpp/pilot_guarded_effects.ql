import cpp
import semmle.code.cpp.controlflow.Guards

// Control dependence of assignments and calls, not vulnerability diagnosis.
from IfStmt branch, GuardCondition guard, Expr effect, Function enclosing,
  boolean testIsTrue
where
  guard = branch.getCondition() and
  enclosing = branch.getEnclosingFunction() and
  enclosing = effect.getEnclosingFunction() and
  enclosing.getLocation().getFile().getRelativePath() = "C/XzDec.c" and
  (effect instanceof Assignment or effect instanceof FunctionCall) and
  guard.controls(effect.getBasicBlock(), testIsTrue) and
  effect.getLocation().getFile().getRelativePath() = "C/XzDec.c"
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
