export const REVIEWER_ID_PATTERN = /^[a-z0-9][a-z0-9-]{1,31}$/;

export function isValidReviewerId(value: string): boolean {
  return REVIEWER_ID_PATTERN.test(value);
}
