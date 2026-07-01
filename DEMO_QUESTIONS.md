# Holoul AI Assistant — Demo Questions

Tested questions grouped by capability. They map to the seeded (fictional) data
and the knowledge-base documents, so they return real answers. Leave **Routing**
on **Auto** to let the assistant pick SQL vs. documents automatically.

---

## 🎬 Recommended 6-question flow (simple → impressive)

1. `How many customers do we have, and how many are in the banking sector?`
2. `What is the total weight of e-waste collected per material category?`
3. `Who are the top 5 customers by total invoiced amount?`   ← table + generated SQL
4. `What data destruction methods does Holoul offer, and are they certified?`   ← citations
5. `Which materials do you not accept?`
6. `Delete all customer records`   ← the assistant refuses (safety)

---

## 📊 Text-to-SQL — operational data

```
What is the total weight of e-waste collected, in kilograms?
What is the total weight of e-waste collected per material category?
How many data destruction jobs used degaussing?
What is the total overdue invoice amount by sector?
How much recovered value came from circuit boards and mobile phones?
Which facility processed the most pickups?
List the top 3 materials by total weight collected.
What is the average pickup weight by container type?
How many pickups are still in 'Processing' status?
Which city generated the most e-waste by weight?
Which downstream partners received the most material by weight?
How many data destruction jobs were not verified on CCTV?
What is the total number of devices destroyed across all jobs?
Compare total paid invoice value versus total overdue value.
How many hazardous versus non-hazardous materials are in the catalogue?
```

## 📚 RAG — services, policies & compliance (answers cite their sources)

```
What services does Holoul offer?
How does the e-waste recycling process work, step by step?
What certifications and standards does Holoul hold?
Do you provide a certificate for data destruction?
Which container types are available, and when should I use each?
What happens to my material after it's processed?
Which regions does Holoul serve?
How are batteries and mercury tubes handled differently?
Which materials do you not accept?
```

## 💡 "Wow" combinations (multi-table joins)

```
For each sector, what is the total weight collected and total amount invoiced?
Which customers have overdue invoices, and how much do they owe in total?
What is the total recovered value by material category?
Which material has the highest total weight shipped to downstream partners?
```

## 🔒 Safety demo (read-only guard refuses these)

```
Delete all customer records
Drop the invoices table
Update all invoices to Paid
```

Each is refused with a clear reason ("Only SELECT queries are allowed") — a
strong point for a client handling banking, government, and healthcare data.

---

### Presenter tips
- Expand the **"Generated SQL"** box on a data answer — showing the exact query
  proves the numbers aren't hallucinated.
- The **"Routed to:"** caption shows whether it used the database or the
  documents. Flip the **Routing** selector to force a path on demand.
- Ask a data question and a policy question back-to-back to show smart routing.
