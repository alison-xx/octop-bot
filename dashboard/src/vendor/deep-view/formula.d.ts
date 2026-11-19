export type FormulaValue = number | boolean | string;
export type FormulaTree = object;
export function compileFormula(
  source: string,
): { tree: FormulaTree; names: string[] } | { error: string };
export function createScope(
  inputs: Map<string, FormulaValue>,
  lets: Map<string, FormulaTree>,
): (name: string) => FormulaValue;
export function evaluate(
  tree: FormulaTree,
  lookup: (name: string) => FormulaValue,
): { value: FormulaValue } | { error: string };
export function show(value: FormulaValue): string;
