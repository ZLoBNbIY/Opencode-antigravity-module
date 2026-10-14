# DeepSeek Web integration

Antigravity Hub is a separate application, not endorsed by DeepSeek. This version
uses a dedicated installed Chrome/Edge profile and the ordinary chat.deepseek.com
page. It does not import Harness grants or call the paid Platform inference API.

The response-fragment parsing and tool-emulation design were informed by the
MIT-licensed Tsuev/opencode-deepseek project (original sums001/Deepseek-API).
The integration itself uses only Python's standard library, installed browsers,
and OpenCode V2. No upstream server or WASM runtime is installed.

The pure-Python DeepSeekHashV1 permutation and PoW challenge format in
`gui-manager/deepseek_pow.py` are adapted from MIT-licensed
`shaohuahuawww/deepseek-pow` (copyright 2026). The required MIT notice is
available at https://github.com/shaohuahuawww/deepseek-pow/blob/main/LICENSE.

MIT License

Copyright (c) 2026 shaohuahuawww

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

The website loads its own scripts and handles its own PoW/human verification.
Service terms, quotas, model availability and website changes still apply.
