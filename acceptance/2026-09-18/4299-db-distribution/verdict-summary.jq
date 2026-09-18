[.data.positions[] | .operations[]] as $ops
| if ($ops|length)==0 then "NO_OPERATIONS"
  else
    ([$ops[] | select(.unit=="米") | "\(.qty)/\(.qty_source)"] | unique | join(",")) as $m
  | ([$ops[] | select(.unit=="折" or .unit=="幅" or .unit=="套") | "\(.qty)/\(.qty_source)"] | unique | join(",")) as $o
  | "米类[\($m)] 折幅套[\($o)] 共\($ops|length)道"
  end
