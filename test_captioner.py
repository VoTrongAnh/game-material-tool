"""Quick test: check what PollinationsCaptioner actually returns."""
from asset_generator import PollinationsCaptioner, PollinationsProvider, DEFAULT_CHARACTER_CAPTION_INSTRUCTION
from PIL import Image
import json

# Step 1: Generate a test sprite
print('=== Generating test sprite... ===')
provider = PollinationsProvider()
result = provider.generate(
    'warrior character, front facing, full body, pixel art, isolated white background',
    width=512, height=512, seed=42,
)
print(f'Image generated: {result.image.size}, mode={result.image.mode}')

# Step 2: Caption it
print('\n=== Captioning with vision model... ===')
captioner = PollinationsCaptioner()
caption = captioner.describe(result.image, instruction=DEFAULT_CHARACTER_CAPTION_INSTRUCTION)

print(f'\n=== CaptionResult fields ===')
print(f'type(description): {type(caption.description)}')
print(f'len(description): {len(caption.description)}')
print(f'description repr: {caption.description!r}')
print(f'warnings: {caption.warnings}')
print(f'provider: {caption.provider}')
print(f'model: {caption.model}')

# Step 3: Check if it looks like JSON
print('\n=== JSON detection ===')
desc = caption.description.strip()
is_json = False
if desc.startswith('{') or desc.startswith('['):
    try:
        parsed = json.loads(desc)
        print(f'WARNING: It IS valid JSON! Parsed type: {type(parsed)}')
        print(f'Parsed: {json.dumps(parsed, indent=2)[:500]}')
        is_json = True
    except json.JSONDecodeError:
        print('Starts with { or [ but is NOT valid JSON')
else:
    print('Not JSON - starts with: ' + repr(desc[:50]))

# Step 4: Check for markdown artifacts
print('\n=== Markdown/formatting check ===')
has_markdown = any(marker in desc for marker in ['**', '##', '- ', '* ', '```', '\n'])
print(f'Contains markdown markers: {has_markdown}')
print(f'Contains newlines: {chr(10) in desc}')
starts_intro = desc.lower().startswith(('the ', 'this ', 'here ', 'in this'))
print(f'Starts with intro phrase: {starts_intro}')

print('\n=== RAW OUTPUT ===')
print(caption.description)
