import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
  	extend: {
  		fontFamily: {
  			sans: [
  				'Inter',
  				'system-ui',
  				'sans-serif'
  			],
  			mono: [
  				'JetBrains Mono',
  				'monospace'
  			]
  		},
  		colors: {
  			border: 'hsl(var(--border))',
  			input: 'hsl(var(--input))',
  			ring: 'hsl(var(--ring))',
  			background: 'hsl(var(--background))',
  			foreground: 'hsl(var(--foreground))',
  			primary: {
  				DEFAULT: 'hsl(var(--primary))',
  				foreground: 'hsl(var(--primary-foreground))'
  			},
  			secondary: {
  				DEFAULT: 'hsl(var(--secondary))',
  				foreground: 'hsl(var(--secondary-foreground))'
  			},
  			destructive: {
  				DEFAULT: 'hsl(var(--destructive))',
  				foreground: 'hsl(var(--destructive-foreground))'
  			},
  			muted: {
  				DEFAULT: 'hsl(var(--muted))',
  				foreground: 'hsl(var(--muted-foreground))'
  			},
  			accent: {
  				DEFAULT: 'hsl(var(--accent))',
  				foreground: 'hsl(var(--accent-foreground))'
  			},
  			card: {
  				DEFAULT: 'hsl(var(--card))',
  				foreground: 'hsl(var(--card-foreground))'
  			},
  			popover: {
  				DEFAULT: 'hsl(var(--popover))',
  				foreground: 'hsl(var(--popover-foreground))'
  			},
  			profit: {
  				DEFAULT: 'hsl(var(--profit))',
  				foreground: 'hsl(var(--profit-foreground))'
  			},
  			loss: {
  				DEFAULT: 'hsl(var(--loss))',
  				foreground: 'hsl(var(--loss-foreground))'
  			},
  			'neutral-signal': {
  				DEFAULT: 'hsl(var(--neutral-signal))',
  				foreground: 'hsl(var(--neutral-signal-foreground))'
  			},
  			'risk-green': {
  				DEFAULT: 'hsl(var(--risk-green))',
  				foreground: 'hsl(var(--risk-green-foreground))'
  			},
  			'risk-yellow': {
  				DEFAULT: 'hsl(var(--risk-yellow))',
  				foreground: 'hsl(var(--risk-yellow-foreground))'
  			},
  			'risk-orange': {
  				DEFAULT: 'hsl(var(--risk-orange))',
  				foreground: 'hsl(var(--risk-orange-foreground))'
  			},
  			'risk-red': {
  				DEFAULT: 'hsl(var(--risk-red))',
  				foreground: 'hsl(var(--risk-red-foreground))'
  			},
  			'regime-calm': 'hsl(var(--regime-calm))',
  			'regime-neutral': 'hsl(var(--regime-neutral))',
  			'regime-risk-off': 'hsl(var(--regime-risk-off))',
  			'regime-volatile': 'hsl(var(--regime-volatile))',
  			'gate-pass': 'hsl(var(--gate-pass))',
  			'gate-fail': 'hsl(var(--gate-fail))',
  			'gate-skip': 'hsl(var(--gate-skip))'
  		},
  		boxShadow: {
  			sm: 'var(--shadow-sm)',
  			DEFAULT: 'var(--shadow-md)',
  			md: 'var(--shadow-md)',
  			lg: 'var(--shadow-lg)'
  		},
  		transitionDuration: {
  			fast: '120ms',
  			base: '200ms'
  		},
  		borderRadius: {
  			lg: 'var(--radius)',
  			md: 'calc(var(--radius) - 2px)',
  			sm: 'calc(var(--radius) - 4px)'
  		},
  		keyframes: {
  			'accordion-down': {
  				from: {
  					height: '0'
  				},
  				to: {
  					height: 'var(--radix-accordion-content-height)'
  				}
  			},
  			'accordion-up': {
  				from: {
  					height: 'var(--radix-accordion-content-height)'
  				},
  				to: {
  					height: '0'
  				}
  			}
  		},
  		animation: {
  			'accordion-down': 'accordion-down 0.2s ease-out',
  			'accordion-up': 'accordion-up 0.2s ease-out'
  		}
  	}
  },
  plugins: [],
};

export default config;
