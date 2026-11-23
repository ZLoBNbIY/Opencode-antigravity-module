// Preloaded before either CLI: no test can make a live HTTP request.
globalThis.fetch = async (url, init) => {
  if (url !== 'https://oauth2.googleapis.com/token' ||
      init.body.get('refresh_token') !== 'private-fixture-refresh')
    throw new Error('Unexpected request');
  switch (process.env.HUB_TEST_OAUTH) {
    case 'refresh':
      return Response.json({ access_token: 'private-successor', expires_in: 3600 });
    case 'invalid':
      return Response.json({ error: 'invalid_grant', error_description: 'private fixture' }, { status: 400 });
    case '429':
      return new Response('private fixture', { status: 429, headers: { 'retry-after': '780' } });
    default:
      throw new Error('Offline test forbids this request');
  }
};
