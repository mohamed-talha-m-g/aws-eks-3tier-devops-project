export const options = {
  stages: [
    { duration: '1m', target: 20 },
    { duration: '4m', target: 50 },
    { duration: '1m', target: 0 },
  ],
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<1000'],
  },
};

export default function () {
  const res = http.get(`${BASE}/api/tasks`);
  check(res, { 'status is 200': (r) => r.status === 200 });
  sleep(0.1);
}