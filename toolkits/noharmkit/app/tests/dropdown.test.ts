import assert from "node:assert/strict";
import test from "node:test";
import { createElement, Fragment } from "react";

import { dropdownOptions, dropdownPosition, matchingOption, moveOption } from "../lib/dropdown";

test("dropdowns preserve numeric and empty values, disabled placeholders, and complete labels", () => {
  const options = dropdownOptions(createElement(Fragment, null,
    createElement("option", { value: "", disabled: true }, "Choose timing"),
    createElement("option", { value: 1 }, "1", " · Severe"),
    createElement("optgroup", { disabled: true }, createElement("option", { value: "future" }, "Future")),
  ));
  assert.deepEqual(options, [
    { value: "", label: "Choose timing", disabled: true },
    { value: "1", label: "1 · Severe", disabled: false },
    { value: "future", label: "Future", disabled: true },
  ]);
});

const options = [
  { value: "", label: "Choose", disabled: true },
  { value: "a", label: "Alpha", disabled: false },
  { value: "b", label: "Beta", disabled: false },
  { value: "c", label: "Bravo", disabled: false },
];

test("arrow navigation skips disabled choices and stays within the menu", () => {
  assert.equal(moveOption(options, -1, 1), 1);
  assert.equal(moveOption(options, -1, -1), 3);
  assert.equal(moveOption(options, 1, -1), 1);
  assert.equal(moveOption(options, 3, 1), 3);
  assert.equal(moveOption(options, 1, 10), 3);
  assert.equal(moveOption(options.map((option) => ({ ...option, disabled: true })), 0, 1), -1);
});

test("typeahead matches full labels, cycles repeated initials, and skips disabled choices", () => {
  assert.equal(matchingOption(options, "br", -1), 3);
  assert.equal(matchingOption(options, "b", 2), 3);
  assert.equal(matchingOption(options, "b", 3), 2);
  assert.equal(matchingOption(options, "choose", 2), 2);
  assert.equal(matchingOption([], "a", -1), -1);
});

test("menus flip above a low trigger and stay inside narrow viewports", () => {
  const below = dropdownPosition({ left: 280, top: 20, bottom: 52, width: 240 }, { width: 390, height: 844 }, 9);
  assert.equal(below.left, 142);
  assert.ok("top" in below);
  assert.equal(below.top, 58);
  assert.equal(below.maxHeight, 288);
  const above = dropdownPosition({ left: 8, top: 790, bottom: 822, width: 420 }, { width: 390, height: 844 }, 9);
  assert.equal(above.left, 8);
  assert.equal(above.width, 374);
  assert.ok("bottom" in above);
  assert.equal(above.bottom, 60);
  assert.equal(above.maxHeight, 288);
});
