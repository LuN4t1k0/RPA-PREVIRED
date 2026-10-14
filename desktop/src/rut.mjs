export function cleanRutInput(value) {
  return String(value ?? "")
    .toUpperCase()
    .replace(/[^0-9K]/g, "")
    .slice(0, 9);
}

export function formatRutInput(value) {
  const clean = cleanRutInput(value);
  if (clean.length <= 1) return clean;

  const body = clean.slice(0, -1).replace(/^0+(?=\d)/, "");
  const verifier = clean.slice(-1);
  const formattedBody = body.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return `${formattedBody}-${verifier}`;
}

export function normalizeRut(value) {
  const clean = cleanRutInput(value);
  if (clean.length <= 1) return clean;
  return `${clean.slice(0, -1)}-${clean.slice(-1)}`;
}

export function isValidRut(value) {
  const clean = cleanRutInput(value);
  if (!/^\d{1,8}[0-9K]$/.test(clean)) return false;

  const body = clean.slice(0, -1);
  const verifier = clean.slice(-1);
  if (Number(body) === 0) return false;

  let sum = 0;
  let multiplier = 2;
  for (let index = body.length - 1; index >= 0; index -= 1) {
    sum += Number(body[index]) * multiplier;
    multiplier = multiplier === 7 ? 2 : multiplier + 1;
  }

  const result = 11 - (sum % 11);
  const expected = result === 11 ? "0" : result === 10 ? "K" : String(result);
  return verifier === expected;
}
