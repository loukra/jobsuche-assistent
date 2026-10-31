import { describe, expect, test } from "bun:test"
import { runCLI } from "./helpers"

function expectJSONError(stderr: string, code: string): void {
  const parsed = JSON.parse(stderr)
  expect(parsed.code).toBe(code)
  expect(typeof parsed.error).toBe("string")
}

describe("flag validation", () => {
  test("a bogus flag exits 1 with a JSON error on stderr", async () => {
    const result = await runCLI(["search", "-q", "Softwareentwickler", "--nonsense", "x"])
    expect(result.exitCode).toBe(1)
    expect(result.stdout).toBe("")
    expectJSONError(result.stderr, "UNKNOWN_FLAG")
  })

  test("search without --query or --location exits 1", async () => {
    const result = await runCLI(["search"])
    expect(result.exitCode).toBe(1)
    expectJSONError(result.stderr, "NO_QUERY")
  })

  test("detail without an id exits 1", async () => {
    const result = await runCLI(["detail"])
    expect(result.exitCode).toBe(1)
    expectJSONError(result.stderr, "NO_ID")
  })

  test("a non-numeric --jobage exits 1", async () => {
    const result = await runCLI(["search", "-q", "test", "--jobage", "woche"])
    expect(result.exitCode).toBe(1)
    expectJSONError(result.stderr, "BAD_ARG")
  })

  test("an invalid --offer-type exits 1", async () => {
    const result = await runCLI(["search", "-q", "test", "--offer-type", "quatsch"])
    expect(result.exitCode).toBe(1)
    expectJSONError(result.stderr, "BAD_ARG")
  })

  test("an unknown command exits 1", async () => {
    const result = await runCLI(["stellenangebote"])
    expect(result.exitCode).toBe(1)
    expectJSONError(result.stderr, "BAD_CMD")
  })
})
