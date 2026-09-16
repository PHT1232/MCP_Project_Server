/** Confirmation gate for unregistering a pcs project from the control panel. */

export function canConfirmProjectDelete(typed: string, projectName: string): boolean {
  return typed.trim() === projectName;
}
