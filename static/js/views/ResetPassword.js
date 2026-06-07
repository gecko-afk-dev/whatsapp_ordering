import { ref, onMounted } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import { api } from '../api.js';

export default {
    template: `
        <div class="flex items-center justify-center min-h-screen animated-bg">
            <div class="glass p-8 rounded-2xl shadow-2xl w-full max-w-md card-hover">
                <div class="text-center mb-8">
                    <h1 class="text-3xl font-bold text-slate-800 tracking-tight">{{ isSetup ? 'Set Your Password' : 'Reset Password' }}</h1>
                    <p class="text-slate-500 mt-2 text-sm">Please enter a new password for your account.</p>
                </div>
                <form v-if="!success" @submit.prevent="submit" class="space-y-5">
                    <div>
                        <label class="block text-sm font-medium text-slate-700 mb-1">New Password</label>
                        <input v-model="password" type="password" required class="input-premium" placeholder="••••••••">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-slate-700 mb-1">Confirm Password</label>
                        <input v-model="confirmPassword" type="password" required class="input-premium" placeholder="••••••••">
                    </div>
                    <button type="submit" :disabled="loading || password !== confirmPassword || password.length < 6" class="w-full btn-primary mt-2 flex justify-center items-center disabled:opacity-50">
                        <span v-if="loading" class="animate-spin h-5 w-5 border-2 border-white border-t-transparent rounded-full mr-2"></span>
                        <span>{{ loading ? 'Saving...' : 'Save Password' }}</span>
                    </button>
                    
                    <p v-if="password !== confirmPassword && confirmPassword" class="text-red-500 text-xs mt-2 text-center">Passwords do not match.</p>
                </form>
                
                <div v-else class="text-center">
                    <div class="w-16 h-16 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-4">
                        <svg class="w-8 h-8 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
                    </div>
                    <p class="text-slate-700 mb-6">Your password has been successfully saved!</p>
                    <button @click="$emit('done')" class="btn-primary w-full">Go to Login</button>
                </div>
                
                <div v-if="error" class="mt-4 p-3 bg-red-50 text-red-600 rounded-lg text-sm border border-red-100 text-center">
                    {{ error }}
                </div>
            </div>
        </div>
    `,
    props: ['token', 'isSetup'],
    emits: ['done'],
    setup(props, { emit }) {
        const password = ref('');
        const confirmPassword = ref('');
        const loading = ref(false);
        const error = ref(null);
        const success = ref(false);

        const submit = async () => {
            loading.value = true;
            error.value = null;
            try {
                const endpoint = props.isSetup ? '/auth/setup-password' : '/auth/reset-password';
                await api.post(endpoint, {
                    token: props.token,
                    new_password: password.value
                });
                success.value = true;
            } catch (err) {
                error.value = err.response?.data?.detail || 'Failed to set password. The link may be expired.';
            } finally {
                loading.value = false;
            }
        };

        return { password, confirmPassword, loading, error, success, submit };
    }
}
