import assert from "node:assert/strict";
import test from "node:test";

import { cleanRutInput, formatRutInput, isValidRut, normalizeRut } from "../src/rut.mjs";


test("formatea mientras el usuario escribe", () => {
  assert.equal(formatRutInput("156440213"), "15.644.021-3");
  assert.equal(formatRutInput("15.644.021-3"), "15.644.021-3");
  assert.equal(formatRutInput("15644021k"), "15.644.021-K");
});

test("normaliza para enviarlo al backend", () => {
  assert.equal(cleanRutInput(" 15.644.021-3 "), "156440213");
  assert.equal(normalizeRut("15.644.021-3"), "15644021-3");
});

test("valida el dígito verificador", () => {
  assert.equal(isValidRut("15.644.021-3"), true);
  assert.equal(isValidRut("12.345.678-5"), true);
  assert.equal(isValidRut("12.345.678-9"), false);
  assert.equal(isValidRut("0-0"), false);
});
