import cpp

// Source locations of candidate observable effects. A field or pointer write
// may still be internal to an operation; consumers must retain that uncertainty.
from Function enclosing, Expr expression, Expr targetExpr, string kind, string targetText
where
  enclosing = expression.getEnclosingFunction() and
  enclosing.getLocation().getFile().getRelativePath().regexpMatch("C/.*") and
  expression.getLocation().getFile().getRelativePath().regexpMatch("C/.*") and
  (
    kind = "return_value" and
    exists(ReturnStmt statement | statement.getExpr() = expression) and
    targetExpr = expression and
    targetText = "return"
    or
    kind = "field_write" and
    exists(Assignment assignment, FieldAccess field |
      assignment.getLValue() = field and expression = assignment and targetExpr = field and
      targetText = field.getTarget().getName())
    or
    kind = "pointer_write" and
    exists(Assignment assignment |
      (assignment.getLValue() instanceof PointerDereferenceExpr or
       assignment.getLValue() instanceof ArrayExpr) and
      expression = assignment and targetExpr = assignment.getLValue() and
      targetText = assignment.getLValue().toString())
  )
select
  enclosing.getLocation().getFile().getRelativePath(),
  enclosing.getLocation().getStartLine(),
  enclosing.getName(),
  kind,
  expression.getLocation().getStartLine(),
  expression.getLocation().getStartColumn(),
  expression.getLocation().getEndLine(),
  expression.getLocation().getEndColumn(),
  targetText,
  targetExpr.getLocation().getStartLine(),
  targetExpr.getLocation().getStartColumn(),
  targetExpr.getLocation().getEndLine(),
  targetExpr.getLocation().getEndColumn()
