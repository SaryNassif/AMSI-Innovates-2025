from openai import OpenAI

client = OpenAI(
  api_key="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"
)

message_input = str(input("Enter Your Prompt:"))

completion = client.chat.completions.create(
  model="gpt-4o-mini",
  messages=[
    {"role": "user", "content": f"{message_input}"}
  ]
)

print(completion.choices[0].message.content)