import http from 'k6/http';
import { check, sleep } from 'k6';

const baseUrl = (__ENV.BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
const duration = __ENV.DURATION || '2m';
const authVus = Number(__ENV.AUTH_VUS || 10);
const stress = (__ENV.STRESS || 'false').toLowerCase() === 'true';

const scenarios = {
  public_health: {
    executor: 'constant-vus',
    vus: 2,
    duration,
    exec: 'publicHealth',
  },
};

if (__ENV.ACCESS_TOKEN) {
  scenarios.authenticated_read = stress
    ? {
        executor: 'ramping-vus',
        startVUs: 1,
        stages: [
          { duration: '2m', target: authVus },
          { duration: '5m', target: authVus * 2 },
          { duration: '2m', target: authVus * 4 },
          { duration: '2m', target: 0 },
        ],
        exec: 'authenticatedRead',
      }
    : {
        executor: 'constant-vus',
        vus: authVus,
        duration,
        exec: 'authenticatedRead',
      };
}

if (__ENV.ACCESS_TOKEN && __ENV.WRITE_PATH && __ENV.WRITE_BODY) {
  scenarios.controlled_write = {
    executor: 'constant-arrival-rate',
    rate: Number(__ENV.WRITE_RPS || 1),
    timeUnit: '1s',
    duration,
    preAllocatedVUs: 2,
    maxVUs: 20,
    exec: 'controlledWrite',
  };
}

export const options = {
  scenarios,
  thresholds: {
    'http_req_failed{endpoint:health}': ['rate<0.01'],
    'http_req_duration{endpoint:health}': ['p(95)<500', 'p(99)<1500'],
    'http_req_failed{endpoint:authenticated_read}': ['rate<0.01'],
    'http_req_duration{endpoint:authenticated_read}': ['p(95)<500', 'p(99)<1500'],
    'http_req_failed{endpoint:controlled_write}': ['rate<0.01'],
    'http_req_duration{endpoint:controlled_write}': ['p(95)<1000'],
  },
};

function authHeaders(extra = {}) {
  return {
    Authorization: `Bearer ${__ENV.ACCESS_TOKEN}`,
    'X-Request-ID': `k6-${__VU}-${__ITER}`,
    ...extra,
  };
}

export function publicHealth() {
  const live = http.get(`${baseUrl}/health/live`, { tags: { endpoint: 'health' } });
  const ready = http.get(`${baseUrl}/health/ready`, { tags: { endpoint: 'health' } });
  check(live, { 'liveness is 200': (response) => response.status === 200 });
  check(ready, { 'readiness is 200': (response) => response.status === 200 });
  sleep(1);
}

export function authenticatedRead() {
  const path = __ENV.AUTH_READ_PATH || '/v1/users/me';
  const response = http.get(`${baseUrl}${path}`, {
    headers: authHeaders(),
    tags: { endpoint: 'authenticated_read' },
  });
  check(response, { 'authenticated read succeeds': (result) => result.status === 200 });
  sleep(0.2);
}

export function controlledWrite() {
  const response = http.post(`${baseUrl}${__ENV.WRITE_PATH}`, __ENV.WRITE_BODY, {
    headers: authHeaders({
      'Content-Type': 'application/json',
      'Idempotency-Key': `k6-${__VU}-${__ITER}`,
    }),
    tags: { endpoint: 'controlled_write' },
  });
  check(response, {
    'controlled write accepted': (result) => [200, 201, 202].includes(result.status),
  });
}
