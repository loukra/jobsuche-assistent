import { describe, expect, test } from "bun:test"
import { runCLI } from "./helpers.js"

// Contract: errors go to stderr as {"error","code"} with exit 1, never to stdout.
function expectJsonError(result: { stdout: string; stderr: string; exitCode: number }, code: string) {
  expect(result.exitCode).toBe(1)
  expect(result.stdout).toBe("")
  const parsed = JSON.parse(result.stderr) as { error: string; code: string }
  expect(parsed.code).toBe(code)
  expect(parsed.error.length).toBeGreaterThan(0)
}

describe("flag validation", () => {
  test("a bogus flag exits 1 rather than being silently ignored", async () => {
    expectJsonError(await runCLI(["search", "-q", "x", "--nonsense", "1"]), "UNKNOWN_FLAG")
  })

  test("search with neither --query nor --location is refused", async () => {
    expectJsonError(await runCLI(["search"]), "NO_CRITERIA")
  })

  test("detail without an id is refused", async () => {
    expectJsonError(await runCLI(["detail"]), "NO_ID")
  })

  test("detail with an id carrying no number is refused", async () => {
    expectJsonError(await runCLI(["detail", "not-a-job"]), "BAD_ID")
  })

  test("a non-numeric --jobage is refused", async () => {
    expectJsonError(await runCLI(["search", "-q", "x", "--jobage", "week"]), "BAD_ARG")
  })

  test("an unsupported --remote mode is refused", async () => {
    expectJsonError(await runCLI(["search", "-q", "x", "--remote", "onsite"]), "BAD_ARG")
  })

  test("an unknown command is refused", async () => {
    expectJsonError(await runCLI(["browse"]), "BAD_CMD")
  })

  test("--help prints usage on stdout and exits 0", async () => {
    const r = await runCLI(["search", "--help"])
    expect(r.exitCode).toBe(0)
    expect(r.stdout).toContain("SEARCH FLAGS")
  })
})
