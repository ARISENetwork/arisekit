// Runs every row of a table-driven test inside one test and names the failing row.
export async function eachCase<T>(cases: readonly T[], name: (c: T) => string, run: (c: T) => unknown): Promise<void> {
  for (const c of cases) {
    try {
      await run(c);
    } catch (error) {
      if (error instanceof Error) {
        // The test runner prints the stack, which captured the message before this prefix.
        const row = `Row "${name(c)}": `;
        error.message = row + error.message;
        if (error.stack) error.stack = row + error.stack;
      }
      throw error;
    }
  }
}
