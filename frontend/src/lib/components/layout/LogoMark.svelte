<script module lang="ts">
	// Process-wide counter. Each LogoMark instance takes the next integer so
	// simultaneously-mounted marks never collide on a global SVG clipPath id.
	// The counter advances identically during SSR and client hydration
	// (instances are created in the same order), so there is no mismatch.
	let instanceCounter = 0;

	function nextLogoMarkId(): number {
		return instanceCounter++;
	}
</script>

<script lang="ts">
	interface Props {
		/** `full` = circuit-trace flask; `simple` = plain flask (favicon-grade). */
		variant?: 'full' | 'simple';
		/** Gates the SMIL pulse animation. Only meaningful for `full`. */
		animated?: boolean;
		/** Rendered width and height, in pixels. */
		size?: number;
		class?: string;
	}

	let {
		variant = 'simple',
		animated = false,
		size = 30,
		class: cls = '',
	}: Props = $props();

	const clipId = `brm-clip-${nextLogoMarkId()}`;

	// Brand-locked palette — the mark never adapts to a theme.
	const TEAL = '#0A4C5C';
	const GREEN = '#1DA570';
	const BONE = '#F4F7F9';
	const AMBER = '#F59A1A';

	const FLASK = 'M 41 14 L 59 14 L 59 38 A 24 24 0 1 1 41 38 Z';
</script>

{#if variant === 'full'}
	<svg
		class={cls}
		width={size}
		height={size}
		viewBox="0 0 100 100"
		fill="none"
		data-variant="full"
		aria-hidden="true"
		style="display:block; overflow:visible;"
	>
		<defs>
			<clipPath id={clipId}>
				<path d={FLASK} />
			</clipPath>
		</defs>
		<g clip-path={`url(#${clipId})`}>
			<rect x="0" y="0" width="100" height="100" fill={BONE} />
			<circle cx="50" cy="60" r="18" fill={GREEN} opacity="0.08" />
			<circle cx="50" cy="60" r="10" fill={GREEN} opacity="0.1" />

			<g
				stroke={GREEN}
				stroke-width="1.5"
				fill="none"
				stroke-linejoin="round"
				stroke-linecap="round"
			>
				<path d="M 50 60 L 50 54 L 42 54 L 42 46 L 38 46" />
				<path d="M 50 60 L 56 60 L 56 50 L 62 50 L 62 46" />
				<path d="M 50 60 L 44 60 L 44 68 L 38 68 L 38 74" />
				<path d="M 50 60 L 64 60 L 64 56 L 70 56" />
			</g>
			<g
				stroke={AMBER}
				stroke-width="1.5"
				fill="none"
				stroke-linejoin="round"
				stroke-linecap="round"
				opacity="0.95"
			>
				<path d="M 50 60 L 50 50 L 46 50 L 46 42" />
				<path d="M 50 60 L 58 60 L 58 68 L 64 68 L 64 74" />
				<path d="M 50 60 L 50 70 L 46 70 L 46 78" />
				<path d="M 50 60 L 36 60 L 36 54 L 32 54" />
			</g>

			<g fill={BONE} stroke={TEAL} stroke-width="0.9">
				<circle cx="38" cy="46" r="1.7" />
				<circle cx="62" cy="46" r="1.7" />
				<circle cx="38" cy="74" r="1.7" />
				<circle cx="70" cy="56" r="1.7" />
			</g>
			<g fill={BONE} stroke={AMBER} stroke-width="0.9">
				<circle cx="46" cy="42" r="1.7" />
				<circle cx="64" cy="74" r="1.7" />
				<circle cx="46" cy="78" r="1.7" />
				<circle cx="32" cy="54" r="1.7" />
			</g>

			<g fill={GREEN}>
				<circle cx="50" cy="54" r="0.9" />
				<circle cx="42" cy="54" r="0.9" />
				<circle cx="42" cy="46" r="0.9" />
				<circle cx="56" cy="60" r="0.9" />
				<circle cx="56" cy="50" r="0.9" />
				<circle cx="62" cy="50" r="0.9" />
				<circle cx="44" cy="60" r="0.9" />
				<circle cx="44" cy="68" r="0.9" />
				<circle cx="38" cy="68" r="0.9" />
				<circle cx="64" cy="60" r="0.9" />
				<circle cx="64" cy="56" r="0.9" />
			</g>
			<g fill={AMBER} opacity="0.9">
				<circle cx="50" cy="50" r="0.9" />
				<circle cx="46" cy="50" r="0.9" />
				<circle cx="58" cy="60" r="0.9" />
				<circle cx="58" cy="68" r="0.9" />
				<circle cx="64" cy="68" r="0.9" />
				<circle cx="50" cy="70" r="0.9" />
				<circle cx="46" cy="70" r="0.9" />
				<circle cx="36" cy="60" r="0.9" />
				<circle cx="36" cy="54" r="0.9" />
			</g>

			<circle
				cx="50"
				cy="60"
				r="3"
				fill={BONE}
				stroke={TEAL}
				stroke-width="1.2"
			/>
			<!-- Static hub core — always rendered so reduced-motion users keep
			     a visible hub even when `animated` is true. -->
			<circle cx="50" cy="60" r="1.3" fill={AMBER} />

			{#if animated}
				<!-- All moving parts live here. The scoped @media rule below
				     hides this group entirely under prefers-reduced-motion. -->
				<g class="brm-anim">
					<circle cx="50" cy="60" r="1.3" fill={AMBER}>
						<animate
							attributeName="opacity"
							values="1;.35;1"
							dur="1.6s"
							repeatCount="indefinite"
						/>
						<animate
							attributeName="r"
							values="1.3;1.8;1.3"
							dur="1.6s"
							repeatCount="indefinite"
						/>
					</circle>
					<circle cx="50" cy="60" r="6" fill={AMBER} opacity="0.18">
						<animate
							attributeName="r"
							values="5;9;5"
							dur="2s"
							repeatCount="indefinite"
						/>
						<animate
							attributeName="opacity"
							values=".28;0;.28"
							dur="2s"
							repeatCount="indefinite"
						/>
					</circle>
					<g fill={BONE}>
						<circle r="1.5">
							<animateMotion
								dur="2.4s"
								repeatCount="indefinite"
								begin="0s"
								path="M 50 60 L 50 54 L 42 54 L 42 46 L 38 46"
							/>
							<animate
								attributeName="opacity"
								values="0;0;1;1;0"
								keyTimes="0;.2;.3;.9;1"
								dur="2.4s"
								repeatCount="indefinite"
							/>
						</circle>
						<circle r="1.5">
							<animateMotion
								dur="2.6s"
								repeatCount="indefinite"
								begin="0.5s"
								path="M 50 60 L 56 60 L 56 50 L 62 50 L 62 46"
							/>
							<animate
								attributeName="opacity"
								values="0;0;1;1;0"
								keyTimes="0;.2;.3;.9;1"
								dur="2.6s"
								repeatCount="indefinite"
								begin="0.5s"
							/>
						</circle>
						<circle r="1.5">
							<animateMotion
								dur="2.5s"
								repeatCount="indefinite"
								begin="1.0s"
								path="M 50 60 L 44 60 L 44 68 L 38 68 L 38 74"
							/>
							<animate
								attributeName="opacity"
								values="0;0;1;1;0"
								keyTimes="0;.2;.3;.9;1"
								dur="2.5s"
								repeatCount="indefinite"
								begin="1.0s"
							/>
						</circle>
						<circle r="1.5">
							<animateMotion
								dur="2.2s"
								repeatCount="indefinite"
								begin="1.5s"
								path="M 50 60 L 64 60 L 64 56 L 70 56"
							/>
							<animate
								attributeName="opacity"
								values="0;0;1;1;0"
								keyTimes="0;.2;.3;.9;1"
								dur="2.2s"
								repeatCount="indefinite"
								begin="1.5s"
							/>
						</circle>
						<circle r="1.5">
							<animateMotion
								dur="2.0s"
								repeatCount="indefinite"
								begin="0.2s"
								path="M 50 60 L 50 50 L 46 50 L 46 42"
							/>
							<animate
								attributeName="opacity"
								values="0;0;1;1;0"
								keyTimes="0;.2;.3;.9;1"
								dur="2.0s"
								repeatCount="indefinite"
								begin="0.2s"
							/>
						</circle>
						<circle r="1.5">
							<animateMotion
								dur="2.8s"
								repeatCount="indefinite"
								begin="0.7s"
								path="M 50 60 L 58 60 L 58 68 L 64 68 L 64 74"
							/>
							<animate
								attributeName="opacity"
								values="0;0;1;1;0"
								keyTimes="0;.2;.3;.9;1"
								dur="2.8s"
								repeatCount="indefinite"
								begin="0.7s"
							/>
						</circle>
						<circle r="1.5">
							<animateMotion
								dur="2.3s"
								repeatCount="indefinite"
								begin="1.2s"
								path="M 50 60 L 50 70 L 46 70 L 46 78"
							/>
							<animate
								attributeName="opacity"
								values="0;0;1;1;0"
								keyTimes="0;.2;.3;.9;1"
								dur="2.3s"
								repeatCount="indefinite"
								begin="1.2s"
							/>
						</circle>
						<circle r="1.5">
							<animateMotion
								dur="2.7s"
								repeatCount="indefinite"
								begin="1.7s"
								path="M 50 60 L 36 60 L 36 54 L 32 54"
							/>
							<animate
								attributeName="opacity"
								values="0;0;1;1;0"
								keyTimes="0;.2;.3;.9;1"
								dur="2.7s"
								repeatCount="indefinite"
								begin="1.7s"
							/>
						</circle>
					</g>
				</g>
			{/if}
		</g>
		<path
			d={FLASK}
			fill="none"
			stroke={TEAL}
			stroke-width="3.4"
			stroke-linejoin="round"
		/>
		<line
			x1="38.5"
			y1="14"
			x2="61.5"
			y2="14"
			stroke={TEAL}
			stroke-width="3.4"
			stroke-linecap="round"
		/>
	</svg>
{:else}
	<svg
		class={cls}
		width={size}
		height={size}
		viewBox="0 0 100 100"
		fill="none"
		data-variant="simple"
		aria-hidden="true"
		style="display:block;"
	>
		<defs>
			<clipPath id={clipId}>
				<path d={FLASK} />
			</clipPath>
		</defs>
		<g clip-path={`url(#${clipId})`}>
			<path d={FLASK} fill={GREEN} />
			<circle cx="50" cy="62" r="6" fill={BONE} />
		</g>
		<path
			d={FLASK}
			fill="none"
			stroke={TEAL}
			stroke-width="6"
			stroke-linejoin="round"
		/>
	</svg>
{/if}

<style>
	@media (prefers-reduced-motion: reduce) {
		.brm-anim {
			display: none;
		}
	}
</style>
