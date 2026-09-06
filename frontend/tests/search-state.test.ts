import { describe, expect, test } from "bun:test";
import { readSearchLocation, searchDefaults } from "../src/features/search/state";
function url(state: unknown) { return `http://reader.local/?reader_search=${encodeURIComponent(JSON.stringify(state))}`; }
describe("search location restoration", () => {
  test("restores reading, selection and the exact result page and scope", () => {
    const state = { query: "家庭备份", filters: { ...searchDefaults, source: "rss", tags: ["资料"], include_read: false }, offset: 40, selectedId: "saved-task", reading: true };
    expect(readSearchLocation(url(state))).toEqual(state);
  });
  test("invalid dates do not break an otherwise valid restored search", () => {
    for (const date_from of ["2026-99-99", "2026-02-30", "not-a-date"]) {
      const state = readSearchLocation(url({ query: "备份", filters: { ...searchDefaults, date_from } }));
      expect(state.query).toBe("备份"); expect(state.filters.date_from).toBe("");
    }
  });
  test("malformed location state falls back to a usable empty search", () => {
    expect(readSearchLocation("http://reader.local/?reader_search=%7Bbroken").query).toBe("");
    expect(readSearchLocation(url({ offset: -20 })).offset).toBe(0);
    expect(readSearchLocation(url({ query: "x".repeat(241) })).query).toBe("");
  });
});

 test("reading requires both a query and a selected archive", () => {
   for (const state of [{ reading: true }, { query: "cache", reading: true }, { selectedId: "saved-task", reading: true }]) {
     expect(readSearchLocation(url(state)).reading).toBe(false);
   }
 });
