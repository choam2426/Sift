import python
import semmle.python.types.FunctionObject

from Call call
where
  call.getLocation().getFile().getRelativePath() = "src/urllib3/response.py" and
  not exists(FunctionObject target, CallNode node |
    node.getNode() = call and
    node = target.getACall()
  )
select
  call.getLocation().getFile().getRelativePath(),
  call.getLocation().getStartLine(),
  call.getFunc().toString()
