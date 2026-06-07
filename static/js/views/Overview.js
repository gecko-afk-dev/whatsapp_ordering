/**
 * Overview.js — Direction B SuperAdmin analytics dashboard
 *
 * For admin role: Stripe/Vercel pitch-black aesthetic with MRR, GMV,
 * Active Kitchens, Suspended Kitchens, and 24h Order Volume.
 *
 * For restaurant_owner / cashier: today's stats in the dark surface theme.
 */
import { ref, computed, onMounted } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import { api } from '../api.js';

// ── Reusable stat card component ──────────────────────────────────────────
const AdminStatCard = {
    props: ['title', 'value', 'sub', 'icon', 'accent', 'trend'],
    template: `
        <div class="card-superadmin p-5 flex flex-col gap-3 card-hover hover-glow-saffron group transition-all duration-200">
            <div class="flex items-start justify-between">
                <div class="w-9 h-9 rounded-xl flex items-center justify-center text-base shrink-0"
                     :style="{ background: accentBg, color: accentColor }">
                    {{ icon }}
                </div>
                <span v-if="trend !== undefined"
                      class="text-xs font-bold px-2 py-0.5 rounded-full"
                      :class="trend >= 0 ? 'text-emerald bg-emerald/10' : 'text-harissa bg-harissa/10'">
                    {{ trend >= 0 ? '↑' : '↓' }} {{ Math.abs(trend) }}%
                </span>
            </div>
            <div>
                <p class="text-xs font-bold text-slate-600 uppercase tracking-[0.1em] mb-1">{{ title }}</p>
                <p class="text-2xl font-black text-slate-100 leading-none">{{ displayValue }}</p>
                <p v-if="sub" class="text-xs text-slate-600 mt-1.5 font-medium">{{ sub }}</p>
            </div>
        </div>
    `,
    computed: {
        displayValue() { return this.value ?? '—'; },
        accentBg() {
            const map = {
                saffron: 'rgba(245,158,11,0.15)',
                emerald: 'rgba(16,185,129,0.15)',
                berry:   'rgba(139,92,246,0.15)',
                harissa: 'rgba(239,68,68,0.15)',
                slate:   'rgba(148,163,184,0.10)',
            };
            return map[this.accent] || map.slate;
        },
        accentColor() {
            const map = {
                saffron: '#F59E0B', emerald: '#10B981',
                berry: '#8B5CF6',  harissa: '#EF4444', slate: '#94a3b8'
            };
            return map[this.accent] || map.slate;
        }
    }
};

const OwnerStatCard = {
    props: ['title', 'value', 'icon', 'accent'],
    template: `
        <div class="card-dark p-5 flex items-center gap-4 card-hover transition-all duration-200">
            <div class="w-11 h-11 rounded-2xl flex items-center justify-center text-xl shrink-0"
                 :style="{ background: accentBg, color: accentColor }">
                {{ icon }}
            </div>
            <div>
                <p class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-0.5">{{ title }}</p>
                <p class="text-2xl font-black text-slate-100">{{ value ?? 0 }}</p>
            </div>
        </div>
    `,
    computed: {
        accentBg()    { const m={saffron:'rgba(245,158,11,0.15)',emerald:'rgba(16,185,129,0.15)',berry:'rgba(139,92,246,0.15)'}; return m[this.accent]||m.saffron; },
        accentColor() { const m={saffron:'#F59E0B',emerald:'#10B981',berry:'#8B5CF6'}; return m[this.accent]||'#F59E0B'; }
    }
};

export default {
    name: 'Overview',
    components: { AdminStatCard, OwnerStatCard },
    template: `
        <div class="space-y-8 animate-fade-in">

            <!-- ════ SUPER-ADMIN VIEW ════ -->
            <template v-if="user.role === 'admin'">
                <div class="flex items-center justify-between">
                    <div>
                        <h2 class="text-2xl font-black text-slate-100">Platform Overview</h2>
                        <p class="text-sm text-slate-600 mt-0.5">Live metrics across all restaurants</p>
                    </div>
                    <button @click="loadStats" id="overview-refresh-btn"
                            class="btn btn-ghost text-xs gap-2">
                        <svg class="w-3.5 h-3.5" :class="loading ? 'animate-spin' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
                        </svg>
                        Refresh
                    </button>
                </div>

                <!-- Skeleton loader -->
                <div v-if="loading" class="grid grid-cols-2 lg:grid-cols-4 gap-4">
                    <div v-for="i in 8" :key="i" class="skeleton h-28 rounded-2xl"></div>
                </div>

                <!-- Admin stat grid -->
                <div v-else>
                    <!-- Row 1: Financial -->
                    <p class="text-xs font-black text-slate-700 uppercase tracking-[0.15em] mb-3">💰 Revenue</p>
                    <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
                        <AdminStatCard
                            title="MRR"
                            :value="fmt(adminStats.mrr, 'MAD')"
                            sub="Monthly recurring"
                            icon="💵"
                            accent="saffron"
                        />
                        <AdminStatCard
                            title="GMV (30d)"
                            :value="fmt(adminStats.gmv_30d, 'MAD')"
                            sub="Gross merch value"
                            icon="📊"
                            accent="emerald"
                        />
                        <AdminStatCard
                            title="Revenue Today"
                            :value="fmt(adminStats.total_revenue_today, 'MAD')"
                            sub="All restaurants"
                            icon="📈"
                            accent="saffron"
                        />
                        <AdminStatCard
                            title="Orders (24h)"
                            :value="adminStats.orders_24h ?? adminStats.total_orders_today ?? 0"
                            sub="Last 24 hours"
                            icon="🧾"
                            accent="berry"
                        />
                    </div>

                    <!-- Row 2: Kitchen Fleet -->
                    <p class="text-xs font-black text-slate-700 uppercase tracking-[0.15em] mb-3">🍳 Kitchen Fleet</p>
                    <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
                        <AdminStatCard
                            title="Total Restaurants"
                            :value="adminStats.total_restaurants ?? 0"
                            icon="🏪"
                            accent="slate"
                        />
                        <AdminStatCard
                            title="Active Kitchens"
                            :value="adminStats.active_restaurants ?? 0"
                            icon="🟢"
                            accent="emerald"
                        />
                        <AdminStatCard
                            title="Suspended"
                            :value="(adminStats.total_restaurants ?? 0) - (adminStats.active_restaurants ?? 0)"
                            icon="🔴"
                            accent="harissa"
                        />
                        <AdminStatCard
                            title="Avg. Order Value"
                            :value="avgOrderValue"
                            sub="All time"
                            icon="⚡"
                            accent="berry"
                        />
                    </div>
                </div>
            </template>

            <!-- ════ RESTAURANT OWNER / CASHIER VIEW ════ -->
            <template v-else-if="['restaurant_owner', 'cashier'].includes(user.role)">
                <div>
                    <h2 class="text-2xl font-black text-slate-100">Today's Overview</h2>
                    <p class="text-sm text-slate-500 mt-0.5">{{ new Date().toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' }) }}</p>
                </div>

                <div v-if="loading" class="grid grid-cols-2 gap-4">
                    <div v-for="i in 4" :key="i" class="skeleton h-24 rounded-2xl"></div>
                </div>

                <div v-else class="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <OwnerStatCard title="Orders Today"   :value="ownerStats.orders"  icon="🧾" accent="saffron"/>
                    <OwnerStatCard v-if="user.role === 'restaurant_owner'"
                                  title="Revenue Today"  :value="fmtMAD(ownerStats.revenue)" icon="💵" accent="emerald"/>
                    <OwnerStatCard title="Pending"        :value="ownerStats.pending ?? '—'"  icon="⏳" accent="berry"/>
                    <OwnerStatCard title="Avg. Order"     :value="ownerStats.avg_order ? fmtMAD(ownerStats.avg_order) : '—'" icon="⚡" accent="saffron"/>
                </div>
            </template>
        </div>
    `,
    props: ['user'],

    setup(props) {
        const loading    = ref(true);
        const adminStats = ref({});
        const ownerStats = ref({ orders: 0, revenue: 0 });

        const fmt    = (v, unit = '') => v != null ? `${Number(v).toLocaleString('fr-MA')} ${unit}`.trim() : '—';
        const fmtMAD = (v) => fmt(v, 'MAD');

        const avgOrderValue = computed(() => {
            const r = adminStats.value.total_revenue_today;
            const o = adminStats.value.total_orders_today;
            if (!r || !o) return '—';
            return fmtMAD((r / o).toFixed(0));
        });

        const loadStats = async () => {
            loading.value = true;
            try {
                if (props.user.role === 'admin') {
                    const res = await api.get('/admin/analytics/summary');
                    adminStats.value = res.data;
                } else if (['restaurant_owner', 'cashier'].includes(props.user.role)) {
                    const res = await api.get('/admin/restaurant/dashboard');
                    ownerStats.value = res.data.today_stats || { orders: 0, revenue: 0 };
                }
            } catch (err) {
                console.error('[Overview] loadStats error', err);
            } finally {
                loading.value = false;
            }
        };

        onMounted(loadStats);

        return { loading, adminStats, ownerStats, loadStats, fmt, fmtMAD, avgOrderValue };
    }
};
