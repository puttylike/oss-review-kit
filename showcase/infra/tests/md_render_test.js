// frontend/index.html의 마크다운 렌더러 테스트. 실행: node tests/md_render_test.js <index.html> [report.md]
const fs = require('fs');
const assert = require('assert');

const html = fs.readFileSync(process.argv[2], 'utf8');
const script = html.split('<script>')[1].split('</script>')[0];
const start = script.indexOf('function esc(s)');
const end = script.indexOf('function showResult');
// 이 저장소의 index.html에서 렌더러 함수만 잘라 실행한다 (외부 입력 아님, 테스트 전용)
eval(script.slice(start, end));

const evil = [
  '# 제목 <img src=x onerror=alert(1)>',
  '| a | b |', '|---|---|',
  '| <script>x</script> | [클릭](javascript:alert(1)) |',
  '- [ok](https://example.com/?a=1&b="2") **굵게**',
  '```', '<b>코드</b>', '```',
].join('\n');
const h = md(evil);
assert(!/<img|<script|<b>/i.test(h), 'raw tags must be escaped');
assert(!/href="javascript/i.test(h), 'javascript: links must not become anchors');
assert(/<a href="https:\/\/example\.com\/\?a=1&amp;b=&quot;2&quot;"/.test(h), 'https link kept, quotes escaped');
assert(/<table>/.test(h) && /<strong>굵게<\/strong>/.test(h) && /<pre><code>&lt;b&gt;/.test(h));
assert(/<ol start="3">/.test(md('3. 셋\n4. 넷')), 'ordered list keeps start number');
console.log('md renderer: XSS and syntax checks OK');

if (process.argv[3]) {
  const rep = md(fs.readFileSync(process.argv[3], 'utf8'));
  const count = (re) => (rep.match(re) || []).length;
  console.log(`report: h1=${count(/<h1>/g)} h2=${count(/<h2>/g)} tables=${count(/<table>/g)} rows=${count(/<tr>/g)}`);
}
