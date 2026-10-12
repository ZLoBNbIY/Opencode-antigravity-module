export function isProviderSecretKey(normalizedKey) {
  return /token|refresh|access|project|fingerprint|deviceid|sessionid|sessiontoken|secret|password|apikey|clientsecret/.test(normalizedKey);
}
