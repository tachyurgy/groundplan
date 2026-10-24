import { expect, meta, test } from './helpers';

// Cloudflare's published IPv4 ranges: the API must never be told one of these is the visitor.
const CF = ['173.245.48.0/20', '103.21.244.0/22', '103.22.200.0/22', '103.31.4.0/22', '141.101.64.0/18', '108.162.192.0/18', '190.93.240.0/20', '188.114.96.0/20', '197.234.240.0/22', '198.41.128.0/17', '162.158.0.0/15', '104.16.0.0/13', '104.24.0.0/14', '172.64.0.0/13', '131.0.72.0/22'];
const toInt = (ip: string) => ip.split('.').reduce((a, o) => (a << 8) + Number(o), 0) >>> 0;
const inCidr = (ip: string, cidr: string) => {
  const [base, bits] = cidr.split('/');
  const mask = bits === '0' ? 0 : (~0 << (32 - Number(bits))) >>> 0;
  return (toInt(ip) & mask) === (toInt(base) & mask);
};

test('the Pages proxy tells the API the visitor IP, not a Cloudflare egress IP', async ({ page, workspace }, info) => {
  test.skip(meta(info).target === 'mock' || meta(info).viewport !== 'desktop', 'proxy exists only on the live stacks; one viewport is enough');
  const r = await page.request.get(`${meta(info).url}/api/v1/workspace`, { headers: { 'X-Workspace-Id': workspace } });
  expect(r.status()).toBe(200);
  expect(r.headers()['x-proxied-by']).toBe('groundplan-pages-function');
  const ip = r.headers()['x-gp-client-ip'];
  expect(ip, 'the proxy forwarded a client IP').toBeTruthy();
  if (/^\d+\.\d+\.\d+\.\d+$/.test(ip)) expect(CF.some((c) => inCidr(ip, c)), `${ip} is a Cloudflare address`).toBe(false);
});
