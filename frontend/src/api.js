// All HTTP access is centralized here. The UI only receives normalized group data.
const STORAGE_KEY = 'owesome.api.v1';
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

function readState() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    return {
      groups: Array.isArray(saved.groups) ? saved.groups : [],
      activeGroupId: saved.activeGroupId || null,
      role: saved.role === 'member' ? 'member' : 'owner',
      currentMemberId: saved.currentMemberId || null,
      memberIds: saved.memberIds || {},
    };
  } catch {
    return { groups: [], activeGroupId: null, role: 'owner', currentMemberId: null, memberIds: {} };
  }
}

function writeState(state) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

async function request(path, { token, method = 'GET', body } = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
  } catch {
    throw new Error(`Can't reach the backend at ${API_BASE_URL}. Start FastAPI and try again.`);
  }
  if (response.status === 204) return null;
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(data?.message || `Backend request failed (${response.status})`);
  return data;
}

function rememberGroup(state, group, tokens = {}) {
  const previous = state.groups.find(item => item.id === group.id) || {};
  const merged = { ...previous, ...group, ...tokens };
  state.groups = [merged, ...state.groups.filter(item => item.id !== group.id)];
  state.activeGroupId = group.id;
  return merged;
}

function normalizeGroup(group, ref, balances) {
  return {
    ...ref,
    ...group,
    simplify: group.simplifyDebts,
    recurring: group.recurringExpenses || [],
    balances: (balances?.balances || []).map(balance => ({
      from: balance.fromMemberId,
      to: balance.toMemberId,
      amount: balance.amount,
    })),
    settlements: (group.settlements || []).map(settlement => ({
      ...settlement,
      from: settlement.fromMemberId,
      to: settlement.toMemberId,
    })),
  };
}

async function loadGroup(ref, role) {
  const token = role === 'owner' ? ref?.ownerToken : ref?.personalToken || ref?.memberToken;
  if (!token) throw new Error(`This browser doesn't have a ${role} link for this group.`);
  const group = await request(`/groups/${encodeURIComponent(token)}`, { token });
  const balances = await request(`/groups/${encodeURIComponent(token)}/balances`, { token });
  return { group, balances };
}

function activeRef(state) {
  const group = state.groups.find(item => item.id === state.activeGroupId);
  if (!group) throw new Error('Choose or create a group first.');
  return group;
}

function ownerToken(group) {
  if (!group.ownerToken) throw new Error('Owner link is required for this action.');
  return group.ownerToken;
}

export const api = {
  async getApp() {
    const state = readState();
    const url = new URL(window.location.href);
    const linkedRole = url.searchParams.has('owner') ? 'owner' : url.searchParams.has('member') ? 'member' : null;
    const linkedToken = linkedRole && url.searchParams.get(linkedRole);

    if (linkedToken) {
      let group;
      try {
        group = await request(`/groups/${encodeURIComponent(linkedToken)}`, { token: linkedToken });
      } catch (error) {
        return { groups: state.groups, activeGroupId: null, role: state.role, currentMemberId: null, error: error.message };
      }
      const accessRole = group.accessRole || linkedRole;
      const links = accessRole === 'owner'
        ? { ownerToken: linkedToken }
        : group.accessMemberId ? { personalToken: linkedToken } : { memberToken: linkedToken };
      rememberGroup(state, group, links);
      state.role = accessRole;
      if (group.accessMemberId) {
        state.currentMemberId = group.accessMemberId;
        state.memberIds[group.id] = group.accessMemberId;
      }
      window.history.replaceState({}, '', `${url.pathname}${url.hash}`);
    }

    const ref = state.groups.find(item => item.id === state.activeGroupId) || state.groups[0];
    if (!ref) return { groups: [], activeGroupId: null, role: state.role, currentMemberId: null };
    state.activeGroupId = ref.id;
    let loaded;
    try {
      loaded = await loadGroup(ref, state.role);
    } catch (error) {
      return { groups: state.groups, activeGroupId: null, role: state.role, currentMemberId: null, error: error.message };
    }
    const { group, balances } = loaded;
    let savedTokens = { ownerToken: ref.ownerToken, memberToken: ref.memberToken };
    if (state.role === 'owner' && !savedTokens.memberToken) {
      const links = await request(`/groups/${encodeURIComponent(ref.ownerToken)}/links`, { token: ref.ownerToken });
      savedTokens.memberToken = links.memberToken;
    }
    const normalized = normalizeGroup(group, ref, balances);
    rememberGroup(state, normalized, savedTokens);
    state.currentMemberId = state.role === 'owner'
      ? normalized.ownerMemberId
      : normalized.accessMemberId || null;
    state.memberIds[normalized.id] = state.currentMemberId;
    writeState(state);
    return { groups: state.groups, activeGroupId: normalized.id, role: state.role, currentMemberId: state.currentMemberId };
  },

  async getSavedGroups(error) {
    const state = readState();
    return { groups: state.groups, activeGroupId: null, role: state.role, currentMemberId: null, error };
  },

  async openGroup(invite) {
    const value = invite.trim();
    if (!value) throw new Error('Paste an owner or member invite link to open a group.');
    let token = value;
    try {
      const url = new URL(value);
      token = url.searchParams.get('owner') || url.searchParams.get('member') || value;
    } catch {
      // A raw token is also accepted.
    }
    const group = await request(`/groups/${encodeURIComponent(token)}`, { token });
    const balances = await request(`/groups/${encodeURIComponent(token)}/balances`, { token });
    const role = group.accessRole || 'member';
    const state = readState();
    const normalized = normalizeGroup(group, {}, balances);
    const tokens = role === 'owner'
      ? { ownerToken: token, ...(await request(`/groups/${encodeURIComponent(token)}/links`, { token })) }
      : group.accessMemberId ? { personalToken: token } : { memberToken: token };
    rememberGroup(state, normalized, tokens);
    state.role = role;
    state.currentMemberId = role === 'owner'
      ? group.ownerMemberId
      : group.accessMemberId || null;
    state.memberIds[group.id] = state.currentMemberId;
    writeState(state);
    return { groups: state.groups, activeGroupId: group.id, role, currentMemberId: state.currentMemberId };
  },

  async selectGroup(id) {
    const state = readState();
    const group = state.groups.find(item => item.id === id);
    if (!group) throw new Error('Group link is not available in this browser.');
    state.activeGroupId = id;
    state.role = group.ownerToken ? 'owner' : 'member';
    writeState(state);
    return this.getApp();
  },

  async joinGroup(name) {
    const state = readState();
    const group = activeRef(state);
    if (!group.memberToken) throw new Error('Open the member invite link to join this group.');
    const member = await request(`/groups/${encodeURIComponent(group.memberToken)}/join`, {
      token: group.memberToken,
      method: 'POST',
      body: { name },
    });
    state.role = 'member';
    state.currentMemberId = member.id;
    group.personalToken = member.accessToken;
    state.memberIds[group.id] = member.id;
    writeState(state);
    return this.getApp();
  },

  async createGroup({ name, currency, creatorName }) {
    const created = await request('/groups', { method: 'POST', body: { name, currency, creatorName } });
    const state = readState();
    rememberGroup(state, created, { ownerToken: created.ownerToken, memberToken: created.memberToken });
    state.role = 'owner';
    state.currentMemberId = created.ownerMemberId;
    state.memberIds[created.id] = state.currentMemberId;
    writeState(state);
    return this.getApp();
  },

  async removeMember(id) {
    const group = activeRef(readState());
    await request(`/groups/${encodeURIComponent(ownerToken(group))}/members/${encodeURIComponent(id)}`, {
      token: group.ownerToken, method: 'DELETE',
    });
    return this.getApp();
  },

  async saveExpense(input) {
    const group = activeRef(readState());
    const token = ownerToken(group);
    const path = `/groups/${encodeURIComponent(token)}/expenses${input.id ? `/${encodeURIComponent(input.id)}` : ''}`;
    const body = {
      description: input.description,
      amount: Number(input.amount),
      category: input.category,
      date: input.date,
      payers: input.payers.map(payer => ({ memberId: payer.memberId, amount: Number(payer.amount) })),
      participants: input.participants,
      splitType: input.splitType,
      ...(input.shares ? { shares: input.shares } : {}),
    };
    await request(path, { token, method: input.id ? 'PUT' : 'POST', body });
    return this.getApp();
  },

  async deleteExpense(id) {
    const group = activeRef(readState());
    const token = ownerToken(group);
    await request(`/groups/${encodeURIComponent(token)}/expenses/${encodeURIComponent(id)}`, { token, method: 'DELETE' });
    return this.getApp();
  },

  async toggleSimplify() {
    const group = activeRef(readState());
    const token = ownerToken(group);
    await request(`/groups/${encodeURIComponent(token)}/settings`, {
      token, method: 'PATCH', body: { simplifyDebts: !group.simplify },
    });
    return this.getApp();
  },

  async markPaid({ to, amount }) {
    const state = readState();
    const group = activeRef(state);
    const token = state.role === 'owner' ? group.ownerToken : group.personalToken;
    if (!token) throw new Error('Join this group from your member invite link before reporting a payment.');
    await request(`/groups/${encodeURIComponent(token)}/settlements`, {
      token, method: 'POST', body: { fromMemberId: state.currentMemberId, toMemberId: to, amount: Number(amount) },
    });
    return this.getApp();
  },

  async confirmSettlement(id) {
    const state = readState();
    const group = activeRef(state);
    const token = state.role === 'owner' ? ownerToken(group) : group.personalToken;
    if (!token) throw new Error('Open your personal member link to confirm this payment.');
    await request(`/groups/${encodeURIComponent(token)}/settlements/${encodeURIComponent(id)}/confirm`, { token, method: 'POST' });
    return this.getApp();
  },

  async addRecurring(input) {
    const group = activeRef(readState());
    const token = ownerToken(group);
    await request(`/groups/${encodeURIComponent(token)}/recurring-expenses`, {
      token, method: 'POST', body: {
        description: input.description,
        amount: Number(input.amount),
        category: input.category,
        interval: input.interval,
      },
    });
    return this.getApp();
  },

  async deleteRecurring(id) {
    const group = activeRef(readState());
    const token = ownerToken(group);
    await request(`/groups/${encodeURIComponent(token)}/recurring-expenses/${encodeURIComponent(id)}`, { token, method: 'DELETE' });
    return this.getApp();
  },

  async getMemberAccessToken(memberId) {
    const group = activeRef(readState());
    const token = ownerToken(group);
    const response = await request(
      `/groups/${encodeURIComponent(token)}/members/${encodeURIComponent(memberId)}/access-link`,
      { token },
    );
    return response.accessToken;
  },
};
