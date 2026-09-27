import cpp

// Declared function parameter names and types in the extracted C source scope.
from Function function, Parameter parameter, int index
where
  parameter = function.getParameter(index) and
  function.getLocation().getFile().getRelativePath().regexpMatch("C/.*")
select
  function.getLocation().getFile().getRelativePath(),
  function.getLocation().getStartLine(),
  function.getName(),
  index,
  parameter.getName(),
  parameter.getType().toString()
