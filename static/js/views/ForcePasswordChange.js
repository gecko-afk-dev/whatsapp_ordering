import { ref } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import { api } from '../api.js';

export default {
    template: `
        <div class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/90 backdrop-blur-sm">
            <div class="bg-white p-8 rounded-2xl shadow-2xl w-full max-w-md">
                <div class="text-center mb-6">
                    <div class="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-4">
                        <svg class="w-8 h-8 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"></path></svg>
                    </div>
                    <h2 class="text-2xl font-bold text-slate-800">Security Update Required</h2>
                    <p class="text-slate-500 mt-2 text-sm">Please update your temporary password to continue to the dashboard.</p>
                </div>
                
                <form @submit.prevent="submit" class="space-y-4">
                    <div>
                        <label class="block text-sm font-medium text-slate-700 mb-1">New Password</label>
                        <input v-model="password" type="password" required class="input-premium border-slate-300">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-slate-700 mb-1">Confirm Password</label>
                        <input v-model="confirmPassword" type="password" required class="input-premium border-slate-300">
                    </div>
                    
                    <button type="submit" :disabled="loading || password !== confirmPassword || password.length < 6" class="w-full btn-primary mt-4 disabled:opacity-50">
                        {{ loading ? 'Saving...' : 'Update Password & Continue' }}
                    </button>
                    <p v-if="password !== confirmPassword && confirmPassword" class="text-red-500 text-xs mt-2 text-center">Passwords do not match.</p>
                </form>
            </div>
        </div>
    `,
    props: ['user'],
    emits: ['updated'],
    setup(props, { emit }) {
        const password = ref('');
        const confirmPassword = ref('');
        const loading = ref(false);

        const submit = async () => {
            // Because they are logged in, we can hit an authenticated endpoint to change password
            // But wait, the reset-password endpoint takes a token. We need to hit a new or existing endpoint to just update their own password.
            // Actually, we didn't build an authenticated change password endpoint. Let's do that quickly via api call if it existed, or we add it to auth.py.
            loading.value = true;
            try {
                // Let's assume we create an endpoint for this in admin.py or auth.py
                await api.post('/auth/force-change-password', { new_password: password.value });
                emit('updated');
            } catch (err) {
                alert("Failed to update password");
            } finally {
                loading.value = false;
            }
        };

        return { password, confirmPassword, loading, submit };
    }
}
