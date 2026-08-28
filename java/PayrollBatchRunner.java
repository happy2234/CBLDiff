/**
 * PayrollBatchRunner.java — CBLDiff Phase 5: Batch execution helper for dual executor.
 *
 * Reads pipe-delimited records from stdin (one per line), calls
 * PayrollProcessor.process() on each, and writes one result per line to stdout.
 *
 * This avoids 70 separate JVM startups by processing all test inputs in a
 * single JVM invocation.
 *
 * Usage:
 *   cat inputs.txt | java -cp java PayrollBatchRunner
 */
import java.util.Scanner;

public class PayrollBatchRunner {
    public static void main(String[] args) {
        Scanner sc = new Scanner(System.in);
        while (sc.hasNextLine()) {
            String line = sc.nextLine().trim();
            if (line.isEmpty() || line.startsWith("#")) {
                continue;
            }
            System.out.println(PayrollProcessor.process(line));
        }
    }
}
